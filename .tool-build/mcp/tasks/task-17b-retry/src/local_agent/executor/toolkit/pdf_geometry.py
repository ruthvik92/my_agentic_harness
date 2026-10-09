"""Extract per-page geometry from a PDF snapshot via pdfinfo."""
import math
import re
import subprocess

_SIZE_RE = re.compile(r"Page\s+\d+\s+size:\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*pts")
_ROT_RE = re.compile(r"Page\s+\d+\s+rot:\s*(\d+)")
_PAGES_RE = re.compile(r"Pages:\s*(\d+)")
_SIZE_FALLBACK_RE = re.compile(r"Page size:\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*pts")
_ROT_FALLBACK_RE = re.compile(r"Page rot:\s*(\d+)")


def _positive_finite(value):
    return value > 0 and math.isfinite(value)


def page_geometry(pdf_snapshot, page):
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be an int >= 1")
    env = {"LC_ALL": "C", "PATH": "/usr/local/bin:/usr/bin:/bin"}
    try:
        proc = subprocess.run(
            ["pdfinfo", "-f", str(page), "-l", str(page), pdf_snapshot],
            capture_output=True,
            check=True,
            timeout=30,
            env=env,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("failed to read pdfinfo output") from exc
    text = proc.stdout.decode("utf-8", "replace")
    pages_match = _PAGES_RE.search(text)
    if not pages_match:
        raise ValueError("malformed pdfinfo output: missing Pages")
    pages = int(pages_match.group(1))
    if page > pages:
        raise ValueError("requested page exceeds page count")
    size_match = _SIZE_RE.search(text) or _SIZE_FALLBACK_RE.search(text)
    if not size_match:
        raise ValueError("malformed pdfinfo output: missing page size")
    width = float(size_match.group(1))
    height = float(size_match.group(2))
    if not (_positive_finite(width) and _positive_finite(height)):
        raise ValueError("malformed pdfinfo output: invalid page size")
    rot_match = _ROT_RE.search(text) or _ROT_FALLBACK_RE.search(text)
    rotation = int(rot_match.group(1)) if rot_match else 0
    if rotation not in (0, 90, 180, 270):
        raise ValueError("malformed pdfinfo output: invalid rotation")
    if rotation in (90, 270):
        width, height = height, width
    return {
        "pages": pages,
        "width_points": width,
        "height_points": height,
        "rotation": rotation,
    }
