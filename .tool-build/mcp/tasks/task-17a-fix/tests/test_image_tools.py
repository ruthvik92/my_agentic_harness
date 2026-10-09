"""Image tool regression tests (Pillow-free where possible; compile-safe)."""
import hashlib
import io
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from local_agent.executor.toolkit import image_info, render_bounds
from local_agent.runtime import image_encoding

W, H = 37, 61


def _png(width, height):
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
            + width.to_bytes(4, "big") + height.to_bytes(4, "big")
            + b"\x08\x02\x00\x00\x00" + b"\x00\x00\x00\x00IEND")


def _jpeg(width, height):
    return (b"\xFF\xD8" + b"\xFF\xC2\x00\x08\x08"
            + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x00")


@pytest.mark.parametrize("data,mime", [
    (_png(W, H), "image/png"),
    (_jpeg(W, H), "image/jpeg"),
])
def test_image_metadata_dimensions_and_hash(data, mime):
    meta = image_info.image_metadata(io.BytesIO(data).read())
    assert meta["mime_type"] == mime
    assert (meta["width"], meta["height"]) == (W, H)
    assert meta["sha256"] == "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("data", [
    b"not-an-image",
    _png(0, 0),
    _png(100000, 100000),
    b"\xFF\xD8\xFF\xC2\x00\x00",
    b"",
])
def test_image_metadata_rejects(data):
    with pytest.raises(ValueError):
        image_info.image_metadata(data)


def test_attachment_jpeg_rgba_transparent():
    from PIL import Image
    img = Image.new("RGBA", (4000, 1500), (255, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = image_encoding.attachment_jpeg(buf.getvalue())
    assert len(out) <= 1024 * 1024
    with Image.open(io.BytesIO(out)) as probe:
        assert max(probe.size) <= 3072
        assert probe.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


@pytest.mark.parametrize("data", [b"", b"garbage-bytes", b"\x89PNG\r\n\x1a\n"])
def test_attachment_jpeg_invalid_raises(data):
    with pytest.raises(ValueError):
        image_encoding.attachment_jpeg(data)


@pytest.mark.parametrize("path", [
    "project/../secret.png",
    "memory/notes.png",
    "project",
    "project/a/b",
])
def test_view_image_rejects_paths(tmp_path, path):
    with pytest.raises(ValueError):
        image_info.view_image({"path": path, "schema_version": 1}, root=str(tmp_path))


def test_view_image_refuses_symlink(tmp_path):
    real = tmp_path / "project"
    real.mkdir()
    target = tmp_path / "real.png"
    target.write_bytes(_png(W, H))
    os.symlink(target, real / "link.png")
    with pytest.raises(ValueError):
        image_info.view_image({"path": "project/link.png", "schema_version": 1}, root=str(tmp_path))


def test_view_image_accepts_valid(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "ok.png").write_bytes(_png(W, H))
    result = image_info.view_image({"path": "project/ok.png", "schema_version": 1}, root=str(tmp_path))
    assert result["width"] == W and result["height"] == H
    assert result["mime_type"] == "image/png"


def test_validate_render_args_accepts():
    pdf, page, region, dpi = render_bounds.validate_render_args(
        {"pdf": "project/a.pdf", "page": 2, "region": [0.1, 0.2, 0.5, 0.7],
         "dpi": 150, "schema_version": 1})
    assert (pdf, page, dpi) == ("project/a.pdf", 2, 150)
    assert list(region) == [0.1, 0.2, 0.5, 0.7]


@pytest.mark.parametrize("args", [
    {"pdf": "project/a.pdf", "page": True, "region": [0, 0, 1, 1]},
    {"pdf": "project/a.pdf", "page": 1, "dpi": 1.5, "region": [0, 0, 1, 1]},
    {"pdf": "project/a.pdf", "page": 1, "region": [float("nan"), 0, 1, 1]},
    {"pdf": "project/a.pdf", "page": 1, "region": [0.9, 0, 0.1, 1]},
    {"pdf": "project/a.pdf", "page": 1},
    {"pdf": "project/a.pdf", "page": 1, "region": [0, 0, 1, 1], "schema_version": 2},
    {"pdf": "project/a.pdf", "page": 1, "region": [0, 0, 1, 1], "bogus": 1},
    {"pdf": "elsewhere/a.pdf", "page": 1, "region": [0, 0, 1, 1]},
])
def test_validate_render_args_rejects(args):
    with pytest.raises(ValueError):
        render_bounds.validate_render_args(args)


@pytest.mark.parametrize("frac,expected", [(0.1, 20), (0.2, 40), (0.5, 80), (0.7, 100)])
def test_crop_rectangle_rounding(frac, expected):
    geometry = {"width_points": 200, "height_points": 200}
    x0, y0, w, h = render_bounds.crop_rectangle(geometry, [frac, frac, 1, 1], 72)
    assert (x0, y0, w, h) == (expected, expected, 200 - expected, 200 - expected)
    assert math.isclose(x0, frac * 200, rel_tol=1e-9)
