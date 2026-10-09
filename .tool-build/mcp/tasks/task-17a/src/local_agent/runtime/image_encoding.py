"""JPEG encoding for image attachments (PNG/JPEG input, bounded output)."""
import io
import warnings

from PIL import Image

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_DIM = 3072
MAX_OUTPUT_BYTES = 1024 * 1024
MIN_DIM = 128


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", image.size, "white")
        return Image.alpha_composite(white, rgba).convert("RGB")
    return image.convert("RGB")


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def attachment_jpeg(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("attachment must be non-empty bytes")
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("attachment exceeds 8 MiB limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(bytes(data))) as probe:
                if probe.format not in ("PNG", "JPEG"):
                    raise ValueError("only PNG/JPEG attachments are supported")
                width, height = probe.size
                if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise ValueError("image dimensions exceed limits")
                probe.verify()
            with Image.open(io.BytesIO(bytes(data))) as image:
                if image.format not in ("PNG", "JPEG"):
                    raise ValueError("only PNG/JPEG attachments are supported")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                    raise ValueError("image dimensions exceed limits")
                image.load()
                rgb = _to_rgb(image)
    except ValueError:
        raise
    except MemoryError:
        raise
    except Exception as exc:
        raise ValueError(f"invalid image data: {exc}") from exc

    if max(rgb.size) > MAX_DIM:
        rgb.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)

    for quality in (90, 75, 60, 45):
        encoded = _encode_jpeg(rgb, quality)
        if len(encoded) <= MAX_OUTPUT_BYTES:
            return encoded

    working = rgb.copy()
    while max(working.size) > MIN_DIM:
        working = working.copy()
        working.thumbnail(
            (max(working.width // 2, MIN_DIM), max(working.height // 2, MIN_DIM)),
            Image.Resampling.LANCZOS,
        )
        encoded = _encode_jpeg(working, 45)
        if len(encoded) <= MAX_OUTPUT_BYTES:
            return encoded
    raise ValueError("unable to encode image within 1 MiB limit")
