"""Validation and crop-bounds math for the render tool. Stdlib math only."""

import math

_FULL_PIXEL_LIMIT = 250_000_000
_CROP_PIXEL_LIMIT = 50_000_000
_ALLOWED_KEYS = {"pdf", "page", "region", "dpi", "schema_version"}


def _strict_int(value):
    if type(value) is not int:
        raise ValueError("expected strict int")
    return value


def _finite_number(value):
    if isinstance(value, bool) or type(value) not in (int, float):
        raise ValueError("expected finite int or float")
    if not math.isfinite(value):
        raise ValueError("expected finite number")
    return value


def validate_render_args(args):
    if not isinstance(args, dict):
        raise ValueError("args must be a dict")
    unknown = set(args) - _ALLOWED_KEYS
    if unknown:
        raise ValueError("unknown keys: %s" % sorted(unknown))
    if "pdf" not in args:
        raise ValueError("missing pdf")
    pdf = args["pdf"]
    if not isinstance(pdf, str) or not pdf.startswith("project/"):
        raise ValueError("pdf must be a string starting with project/")
    if "page" not in args:
        raise ValueError("missing page")
    page = _strict_int(args["page"])
    if page < 1:
        raise ValueError("page must be >= 1")
    dpi = args.get("dpi", 600)
    dpi = _strict_int(dpi)
    if not 72 <= dpi <= 1200:
        raise ValueError("dpi must be 72..1200")
    region = args.get("region")
    if region is not None:
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            raise ValueError("region must be a 4-element list/tuple")
        left, top, right, bottom = (_finite_number(v) for v in region)
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("region must satisfy 0<=left<right<=1, 0<=top<bottom<=1")
    sv = args.get("schema_version")
    if sv is not None:
        if type(sv) is not int or sv != 1:
            raise ValueError("schema_version must be int 1")
    return pdf, page, region, dpi


def crop_rectangle(geometry, region, dpi):
    if not isinstance(geometry, dict):
        raise ValueError("geometry must be a dict")
    width = _finite_number(geometry.get("width_points"))
    height = _finite_number(geometry.get("height_points"))
    if width <= 0 or height <= 0:
        raise ValueError("geometry dimensions must be positive")
    full_w = math.ceil(width * dpi / 72)
    full_h = math.ceil(height * dpi / 72)
    if full_w * full_h > _FULL_PIXEL_LIMIT:
        raise ValueError("full render exceeds pixel limit")
    if region is None:
        return 0, 0, full_w, full_h
    left, top, right, bottom = region
    x0 = math.floor(left * full_w)
    y0 = math.floor(top * full_h)
    x1 = math.ceil(right * full_w)
    y1 = math.ceil(bottom * full_h)
    w = x1 - x0
    h = y1 - y0
    if w < 1 or h < 1:
        raise ValueError("crop rectangle too small")
    if w * h > _CROP_PIXEL_LIMIT:
        raise ValueError("crop exceeds pixel limit")
    return x0, y0, w, h
