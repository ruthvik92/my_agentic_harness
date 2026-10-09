import base64
from pathlib import Path

from .circuits import run_circuit
from .images import run_screenshot
from .profiles import choose


def register_modalities(
    mcp, root: Path, data_root: Path, allowed_roots: list[Path], catalog
) -> None:
    def allowed(path: str) -> Path:
        p = Path(path).resolve()
        for root in allowed_roots:
            if p.is_relative_to(root):
                return p
        raise ValueError("Path outside allowed roots")

    @mcp.tool()
    async def harness_screenshot(
        question: str,
        image_path: str | None = None,
        image_base64: str | None = None,
        history: list[dict] | None = None,
        model: str | None = None,
    ) -> dict:
        """Local vision screenshot question; PNG/JPEG raw base64 or allowlisted host image path, history bounded, unverified reply. Reject both image inputs supplied."""
        if image_path is not None and image_base64 is not None:
            raise ValueError("Both image_path and image_base64 supplied")
        if image_path is None and image_base64 is None:
            raise ValueError("Either image_path or image_base64 must be supplied")
        if image_path is not None:
            p = allowed(image_path)
            if not p.is_file():
                raise ValueError("image_path is not a file")
            with p.open("rb") as stream:
                data = stream.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError("image_path exceeds 4MiB")
            image_base64 = base64.b64encode(data).decode("ascii")
        cfg = choose("screenshot", model, catalog(), root)
        return await run_screenshot(question, image_base64, history, cfg, data_root, root)

    @mcp.tool()
    async def harness_circuit(
        case: str,
        pdf: str,
        page: int,
        question: str,
        region: list[float] | None = None,
        model: str | None = None,
    ) -> dict:
        """Local schematic PDF extraction/netlist analysis; page1-based, region x0,y0,x1,y1 normalized; writes draft exports into case analysis/netlists; caller reviews."""
        case_path = allowed(case)
        if not case_path.is_dir():
            raise ValueError("case_path is not a directory")
        cfg = choose("circuit", model, catalog(), root)
        return await run_circuit(case_path, pdf, page, question, region, cfg, data_root, root)
