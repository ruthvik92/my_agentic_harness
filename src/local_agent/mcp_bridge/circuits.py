import json
import math
import sys
import tempfile
from pathlib import Path

from local_agent.contracts import AgentConfig
from local_agent.mcp_bridge.process import run_cli


async def run_circuit(
    case: Path,
    pdf: str,
    page: int,
    question: str,
    region: list[float] | None,
    config: AgentConfig,
    data_root: Path,
    harness_root: Path,
) -> dict:
    if config.provider != "ollama":
        raise ValueError("Invalid config.provider")
    if not case.resolve().is_dir():
        raise ValueError("Invalid case path")
    if page < 1:
        raise ValueError("Invalid page")
    if not question.strip():
        raise ValueError("Empty question")
    if len(question) > 8000:
        raise ValueError("Question too long")

    resolved_case = case.resolve()
    resolved_pdf = (resolved_case / pdf).resolve()
    if Path(pdf).is_absolute() or ".." in Path(pdf).parts:
        raise ValueError("Invalid PDF path")
    if not resolved_pdf.is_file():
        raise ValueError("PDF not found")
    if not resolved_pdf.is_relative_to(resolved_case):
        raise ValueError("PDF not relative to case")

    if region is not None:
        if len(region) != 4:
            raise ValueError("Region must have 4 values")
        if not all(math.isfinite(v) for v in region):
            raise ValueError("Region values must be finite")
        if not all(0 <= v <= 1 for v in region):
            raise ValueError("Region values must be in [0,1]")
        if not (region[0] < region[2] and region[1] < region[3]):
            raise ValueError("Invalid region bounds")

    data_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=data_root, prefix="mcp-circuit-") as tmpdir:
        agent_path = Path(tmpdir) / "agent.json"
        agent_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
        agent_path.chmod(0o600)

        argv = [
            sys.executable,
            "-m",
            "local_agent.cli",
            "--data-root",
            str(data_root),
            "circuit",
            "--agent",
            str(agent_path),
            "--case",
            str(resolved_case),
            "--pdf",
            pdf,
            "--page",
            str(page),
            "--question",
            question,
            "--dpi",
            "300",
        ]
        if region:
            argv.extend(["--region"] + [str(v) for v in region])

        cli_result = await run_cli(argv, harness_root, config.limits.run_timeout_seconds + 30)

        try:
            stdout = cli_result["stdout"]
            parsed = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as e:
            raise ValueError("Invalid JSON from CLI") from e

        if not isinstance(parsed, dict) or not isinstance(parsed.get("run_id"), str):
            raise ValueError("Missing run_id in CLI output")

        return {
            **parsed,
            "provider": config.provider,
            "model": config.model,
            "exit_code": cli_result["exit_code"],
        }
