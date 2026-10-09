"""Mobile LAN screenshot interface for local-agent harness.

This module implements a ScreenshotAgent subclass and a phone-web server
for answering questions about screenshots via a trusted local network.
"""

import base64
import binascii
import io
import warnings

from PIL import Image, UnidentifiedImageError

from local_agent.runtime.agent import Agent


def validate_request(value: dict) -> dict:
    """Validate and normalize a screenshot request.

    Args:
        value: Raw request dict.

    Returns:
        Normalized dict with keys: question, history, image.

    Raises:
        ValueError: On validation errors with safe explanations.
    """
    allowed_keys = {"question", "history", "image"}
    if not isinstance(value, dict) or set(value) - allowed_keys or "question" not in value:
        raise ValueError("Request requires question and permits only history and image")

    question = value.get("question", "")
    if not isinstance(question, str):
        raise ValueError("question must be a non-empty string")
    if not question.strip():
        raise ValueError("question must be non-empty")
    if len(question) > 8000:
        raise ValueError("question length must not exceed 8000 characters")

    history = value.get("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be a list")
    if len(history) > 12:
        raise ValueError("history must contain at most 12 messages")
    for i, msg in enumerate(history):
        if not isinstance(msg, dict):
            raise ValueError(f"history[{i}] must be a dict")
        if set(msg.keys()) != {"role", "content"}:
            raise ValueError(f"history[{i}] keys must be exactly role/content")
        role = msg.get("role")
        content = msg.get("content")
        if not isinstance(role, str) or role not in {"user", "assistant"}:
            raise ValueError(f"history[{i}] role must be user or assistant")
        if not isinstance(content, str):
            raise ValueError(f"history[{i}] content must be a string")
        if len(content) > 16000:
            raise ValueError(f"history[{i}] content length must not exceed 16000")

    if sum(len(msg["content"]) for msg in history) > 16000:
        raise ValueError("history total content must not exceed 16000 characters")

    image = value.get("image")
    if "image" in value:
        if not isinstance(image, str):
            raise ValueError("image must be a string or omitted")
        if not image:
            raise ValueError("image must be non-empty if present")
        if image.startswith("data:"):
            raise ValueError("image must not include data URL prefix")
        if len(image) > 4 * ((4 * 1024 * 1024 + 2) // 3):
            raise ValueError("image base64 length must not exceed ceil(4MiB)")
        try:
            raw_bytes = base64.b64decode(image, validate=True)
        except binascii.Error as exc:
            raise ValueError("image base64 decode failed") from exc
        if len(raw_bytes) > 4 * 1024 * 1024:
            raise ValueError("decoded image size must not exceed 4MiB")
        image_mime(raw_bytes)

    normalized = {"question": question, "history": history}
    if "image" in value:
        normalized["image"] = image
    return normalized


def image_mime(raw_bytes: bytes) -> str:
    """Validate raw image bytes and return MIME type.

    Args:
        raw_bytes: Decoded image bytes.

    Returns:
        'image/png' or 'image/jpeg'.

    Raises:
        ValueError: On validation errors.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw_bytes)) as img:
                if img.format not in {"PNG", "JPEG"}:
                    raise ValueError("image format must be PNG or JPEG")
                if img.width <= 0 or img.height <= 0 or img.width * img.height > 16_000_000:
                    raise ValueError("image pixel count must be positive and at most 16 million")
                mime = "image/png" if img.format == "PNG" else "image/jpeg"
                img.verify()
                return mime
    except (
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
    ) as exc:
        raise ValueError("image is malformed or a decompression bomb") from exc


class ScreenshotAgent(Agent):
    """Agent specialized for answering questions about screenshots.

    - Accepts a question, optional base64-encoded PNG/JPEG image, and recent history.
    - Validates input strictly.
    - Stores image and history as immutable blobs.
    - Uses Ollama vision model with no tools.
    - Dispatches to phone-v1 instruction set.
    """

    def __init__(self, *args, request=None, **kwargs):
        if request is not None:
            self.input_request = validate_request(request)
        else:
            self.input_request = None
        super().__init__(*args, **kwargs)
        if self.config.instructions_version != "phone-v1":
            raise ValueError("config.instructions_version must be 'phone-v1'")
        if self.config.tools != ():
            raise ValueError("config.tools must be an empty tuple")

    async def prepare(self):
        if self.input_request is None:
            raise ValueError("request must not be None")
        selected = next(
            (e for e in self.store.events(self.run_id) if e.event_type == "model.selected"),
            None,
        )
        if selected is None:
            raise ValueError("model.selected event not found")
        metadata = self.store.blobs.json(selected.data["metadata_ref"])
        if (
            self.input_request.get("image")
            and self.config.provider == "ollama"
            and not metadata.get("scripted")
        ):
            if "vision" not in metadata["show"]["capabilities"]:
                raise ValueError("vision capability required for image with ollama provider")
        raw_image = self.input_request.get("image")
        if raw_image is not None:
            raw_bytes = base64.b64decode(raw_image, validate=True)
            mime = image_mime(raw_bytes)
            ref = self.store.blobs.put(raw_bytes)
            with Image.open(io.BytesIO(raw_bytes)) as uploaded:
                image_info = {
                    "width": uploaded.width,
                    "height": uploaded.height,
                    "bytes": len(raw_bytes),
                    "mime": mime,
                }
        else:
            ref = None
            mime = None
            image_info = None
        history = self.input_request.get("history", [])
        history_ref = self.store.blobs.put_json(history)
        self.event(
            "screenshot.prepared",
            "runtime",
            {
                "input_ref": self.store.blobs.put_json(
                    {
                        "image_ref": ref,
                        "mime": mime,
                        "history_ref": history_ref,
                        "image_info": image_info,
                    }
                )
            },
        )

    def prepared(self):
        for e in reversed(self.store.events(self.run_id)):
            if e.event_type == "screenshot.prepared":
                return self.store.blobs.json(e.data["input_ref"])
        raise ValueError("screenshot.prepared event not found; run must be fresh")

    def fixed_messages(self, task):
        manifest = self.prepared()
        history = self.store.blobs.json(manifest["history_ref"])
        diagnostic = (
            "Harness upload diagnostics: phone mode can see submitted images and recent chat only; "
            "it has no filesystem or command tools. Server accepts prepared PNG/JPEG images up to "
            "4 MiB and 16 million pixels; JSON request limit is 6 MiB. Browser chooses image files "
            "up to 20 MiB, checks actual decode rather than reported MIME, converts other decodable "
            "formats and downsizes large images to fit. If the photo picker itself says Unable to "
            "load before selection reaches the page, save/export a local PNG/JPEG copy and select "
            "it from Files/Browse. Unsupported formats must be exported to PNG/JPEG. "
            "Attachment for THIS request: "
            + (
                str(manifest.get("image_info") or {"mime": manifest["mime"]})
                if manifest["image_ref"]
                else "none; no image was submitted."
            )
        )
        messages = [
            {"role": "system", "content": self.instructions},
            {"role": "system", "content": diagnostic},
            *history,
        ]
        if manifest["image_ref"] is None:
            messages.append({"role": "user", "content": task})
        else:
            raw_bytes = self.store.blobs.read(manifest["image_ref"])
            base64_image = base64.b64encode(raw_bytes).decode("ascii")
            if self.config.provider == "ollama":
                messages.append({"role": "user", "content": task, "images": [base64_image]})
            else:
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": task},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{manifest['mime']};base64,{base64_image}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                )
        return messages
