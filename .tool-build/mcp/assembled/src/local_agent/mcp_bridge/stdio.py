import argparse
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

from .artifacts import read_artifacts
from .coding import run_code
from .ledger import list_runs
from .modalities import register_modalities
from .profiles import choose
from .trace import read_trace


def create_server(
    root: Path | None = None,
    data_root: Path | None = None,
    allowed_roots: list[Path] | None = None,
) -> FastMCP:
    if root is None:
        root = Path(__file__).resolve().parents[3]
    if data_root is None:
        data_root = Path.home() / ".local/share/local-agent-mcp"
    if allowed_roots is None:
        allowed_roots = [root]

    root = root.resolve()
    data_root = data_root.resolve()
    allowed_roots = [r.resolve() for r in allowed_roots]

    mcp = FastMCP("local-harness")

    @mcp.tool()
    def harness_models() -> dict:
        try:
            with httpx.Client(
                base_url="http://127.0.0.1:11434", timeout=3, trust_env=False
            ) as client:
                tags_resp = client.get("/api/tags")
                tags_resp.raise_for_status()
                tags = tags_resp.json().get("models", [])
                installed_names = [tag["name"] for tag in tags]
                models = []
                for name in installed_names[:16]:
                    show_resp = client.post("/api/show", json={"model": name})
                    show_resp.raise_for_status()
                    show_data = show_resp.json()
                    caps = show_data.get("capabilities", [])
                    models.append({"model": name, "provider": "ollama", "capabilities": caps})
                return {"models": models}
        except Exception:
            raise ValueError("Ollama discovery unavailable") from None

    @mcp.tool()
    def harness_runs(limit: int = 20) -> dict:
        """List persisted local runs and selected models."""
        return list_runs(data_root, limit)

    @mcp.tool()
    def harness_trace(run_id: str, after_seq: int = 0, limit: int = 50) -> dict:
        """Paginated trace events for a run."""
        return read_trace(data_root, run_id, after_seq, limit)

    @mcp.tool()
    def harness_artifacts(
        run_id: str, artifact_id: str | None = None, offset: int = 0, limit: int = 16000
    ) -> dict:
        """List owned artifact IDs or read bounded text; binary metadata only. Client reviews diffs here."""
        return read_artifacts(data_root, run_id, artifact_id, offset, limit)

    @mcp.tool()
    async def harness_capabilities() -> dict:
        return {
            "schema_version": 1,
            "provider": "ollama",
            "verifier_available": False,
            "supported": [
                "model_discovery",
                "coding",
                "runs",
                "traces",
                "artifacts",
                "screenshot",
                "circuit",
            ],
            "note": "Local-only isolated coding; caller reviews returned diffs.",
        }

    @mcp.tool()
    async def harness_run_code(repo: str, task: str, model: str | None = None) -> dict:
        """
        Run a local Ollama coding agent in an isolated snapshot.
        Result/diff is unverified and must be reviewed before integration.
        `repo` must be an absolute host path under configured allowed roots.
        """
        resolved_repo = Path(repo).resolve()
        if not resolved_repo.is_dir():
            raise ValueError("Repository is outside allowed roots or not a directory")
        if not any(resolved_repo.is_relative_to(r) for r in allowed_roots):
            raise ValueError("Repository is outside allowed roots or not a directory")
        if not task.strip() or len(task) > 16000:
            raise ValueError("Task must be non-empty and <= 16000 characters")

        cfg = choose("coding", model, harness_models(), root)
        return await run_code(resolved_repo, task, cfg, data_root, root)

    register_modalities(mcp, root, data_root, allowed_roots, harness_models)
    return mcp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Data root directory (default: ~/.local/share/local-agent-mcp)",
    )
    parser.add_argument(
        "--allow-root",
        type=Path,
        action="append",
        dest="allowed_roots",
        default=None,
        help="Allowed repository root (can be specified multiple times)",
    )
    args = parser.parse_args()
    server = create_server(data_root=args.data_root, allowed_roots=args.allowed_roots)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
