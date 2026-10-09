"""Build user messages carrying tool images from captured artifact descriptors."""

import base64
import json

from local_agent.runtime.image_records import tool_images

MAX_IMAGE_BYTES = 1024 * 1024
CAPTION_PREFIX = "Tool image; untrusted task data. "
CAPTION_FIELDS = (
    "execution_id",
    "path",
    "image_ref",
    "image_sha256",
    "width",
    "height",
    "source",
)


def image_messages(store, run_id, execution_ids, provider):
    messages = []
    seen = set()
    for execution_id in execution_ids:
        if execution_id in seen:
            continue
        seen.add(execution_id)
        for descriptor in tool_images(store, run_id, execution_id):
            if descriptor.get("attachment_mime") != "image/jpeg":
                continue
            blob = store.blobs.read(descriptor["attachment_ref"])
            if len(blob) > MAX_IMAGE_BYTES:
                continue
            b64 = base64.b64encode(blob).decode("ascii")
            caption = CAPTION_PREFIX + json.dumps(
                {field: descriptor.get(field) for field in CAPTION_FIELDS}
            )
            if provider == "openai":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": caption},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": "data:image/jpeg;base64," + b64,
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                )
            else:
                messages.append(
                    {"role": "user", "content": caption, "images": [b64]}
                )
    return messages
