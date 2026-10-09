"""Trusted fixed PDF rendering entrypoint, executed only inside the offline image."""

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--pdf", required=True)
parser.add_argument("--page", required=True, type=int)
parser.add_argument("--dpi", type=int, default=300)
parser.add_argument("--region", type=float, nargs=4)
parser.add_argument("--context-page", type=int)
args = parser.parse_args()
source = Path(args.pdf).resolve(strict=True)
if not source.is_relative_to(Path("/workspace/project")) or not source.is_file():
    raise ValueError("PDF must be an imported project file")
if not 72 <= args.dpi <= 600 or args.page < 1:
    raise ValueError("invalid page or DPI")
info = subprocess.check_output(
    ["pdfinfo", "-f", str(args.page), "-l", str(args.page), str(source)], timeout=30
).decode()
# Scanned manuals may have empty text. Rendering, not text extraction, supplies vision.
lines = info.splitlines()
pages = int(next(line.split(":", 1)[1] for line in lines if line.startswith("Pages:")))
if args.page > pages or args.context_page and not 1 <= args.context_page <= pages:
    raise ValueError("page out of range")
output = Path("/workspace/project/extracted") / f"page-{args.page:03d}"
output.mkdir(parents=True, exist_ok=False)
images = []


def render(page, label, dpi, crop=None):
    page_info = subprocess.check_output(
        ["pdfinfo", "-f", str(page), "-l", str(page), str(source)], timeout=30
    ).decode()
    size = next(line for line in page_info.splitlines() if "size:" in line and "pts" in line)
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+pts", size)
    width, height = [math.ceil(float(v) * dpi / 72) for v in match.groups()]
    if width * height > 50_000_000:
        raise ValueError("render exceeds 50 megapixel cap")
    prefix = output / label
    argv = ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(dpi), "-singlefile", "-png"]
    if crop:
        left, top, right, bottom = crop
        argv += [
            "-x",
            str(int(left * width)),
            "-y",
            str(int(top * height)),
            "-W",
            str(math.ceil((right - left) * width)),
            "-H",
            str(math.ceil((bottom - top) * height)),
        ]
    subprocess.run([*argv, str(source), str(prefix)], timeout=120, check=True)
    data = prefix.with_suffix(".png").read_bytes()
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("rendered PNG exceeds 8 MiB capture limit")
    images.append(
        {
            "path": str(prefix.with_suffix(".png").relative_to("/workspace/project")),
            "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
            "page": page,
            "dpi": dpi,
            "region": crop or [0, 0, 1, 1],
            "label": label,
        }
    )


render(args.page, "full", args.dpi)
if args.region:
    left, top, right, bottom = args.region
    if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
        raise ValueError("region must be normalized left top right bottom")
    render(args.page, "region", min(600, args.dpi * 2), args.region)
else:
    for label, crop in [
        ("top-left", [0, 0, 0.55, 0.55]),
        ("top-right", [0.45, 0, 1, 0.55]),
        ("bottom-left", [0, 0.45, 0.55, 1]),
        ("bottom-right", [0.45, 0.45, 1, 1]),
    ]:
        render(args.page, label, min(600, args.dpi * 2), crop)
if args.context_page:
    render(args.context_page, f"context-{args.context_page:03d}", args.dpi)
subprocess.run(
    [
        "pdftotext",
        "-f",
        str(args.page),
        "-l",
        str(args.page),
        "-layout",
        str(source),
        str(output / "text.txt"),
    ],
    timeout=30,
    check=True,
)
hash_value = hashlib.sha256()
with source.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        hash_value.update(chunk)
manifest = {
    "schema_version": 1,
    "pdf_hash": "sha256:" + hash_value.hexdigest(),
    "pdf_filename": source.name,
    "page": args.page,
    "page_count": pages,
    "page_convention": "one-based PDF page, not printed page label",
    "images": images,
    "text_path": str((output / "text.txt").relative_to("/workspace/project")),
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps(manifest))
