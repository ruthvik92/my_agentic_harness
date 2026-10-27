"""Image header metadata toolkit (stdlib only)."""
import hashlib

_MAX_BYTES = 8 * 1024 * 1024
_MAX_PIXELS = 50 * 1000 * 1000
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_SOF = (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF)
_ALLOWED = ("project", "tools", "scratch", "outputs")


def _png_dimensions(data):
    if len(data) < 24 or data[:8] != _PNG_SIG or data[12:16] != b"IHDR":
        raise ValueError("not a valid PNG header")
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _jpeg_dimensions(data):
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        raise ValueError("not a valid JPEG header")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise ValueError("malformed JPEG segment")
        marker = data[pos + 1]
        if marker == 0xD9:
            break
        if marker == 0xD8 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if pos + 4 > len(data):
            raise ValueError("truncated JPEG segment length")
        seg_len = int.from_bytes(data[pos + 2:pos + 4], "big")
        if seg_len < 2 or pos + 2 + seg_len > len(data):
            raise ValueError("truncated JPEG segment")
        if marker in _SOF:
            if pos + 9 > len(data):
                raise ValueError("truncated SOF segment")
            height = int.from_bytes(data[pos + 5:pos + 7], "big")
            width = int.from_bytes(data[pos + 7:pos + 9], "big")
            return width, height
        pos += 2 + seg_len
    raise ValueError("no supported SOF marker found")


def image_metadata(data):
    if isinstance(data, memoryview):
        data = bytes(data)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    data = bytes(data)
    if not data:
        raise ValueError("empty data")
    if len(data) > _MAX_BYTES:
        raise ValueError("data exceeds 8MiB limit")
    if data[:8] == _PNG_SIG:
        mime, width, height = "image/png", *_png_dimensions(data)
    elif len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8:
        mime, width, height = "image/jpeg", *_jpeg_dimensions(data)
    else:
        raise ValueError("unsupported image type; only PNG/JPEG accepted")
    if width <= 0 or height <= 0:
        raise ValueError("zero or negative dimensions")
    if width * height > _MAX_PIXELS:
        raise ValueError("image exceeds 50M pixel limit")
    return {
        "mime_type": mime,
        "width": width,
        "height": height,
        "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
    }


def view_image(args, root="/workspace"):
    if not isinstance(args, dict):
        raise ValueError("args must be a dict")
    if set(args) - {"path", "schema_version"}:
        raise ValueError("unknown args: %s" % sorted(set(args) - {"path", "schema_version"}))
    if "schema_version" in args and (type(args["schema_version"]) is not int or args["schema_version"] != 1):
        raise ValueError("unsupported schema_version")
    path = args.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("path is required")
    parts = path.split("/")
    if len(parts) < 2 or parts[0] not in _ALLOWED or any(p in ("", ".", "..") for p in parts):
        raise ValueError("path must start with project/, tools/, scratch/, or outputs/")
    from . import workspace_io

    data = workspace_io.read_bytes(path, limit=_MAX_BYTES, root=root)
    result = {"kind": "image", "path": path}
    result.update(image_metadata(data))
    return result
