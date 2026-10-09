import json
import sys
import tempfile
from pathlib import Path

from local_agent.contracts import AgentConfig
from local_agent.mobile import validate_request

from .process import run_cli


async def run_screenshot(
    question: str,
    image: str | None,
    history: list | None,
    config: AgentConfig,
    data_root: Path,
    harness_root: Path,
) -> dict:
    request = {"question": question, "history": history or []}
    if image is not None:
        request["image"] = image
    validate_request(request)
    if config.provider != "ollama":
        raise ValueError("Provider must be ollama")
    data_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=data_root, prefix="mcp-image-") as tmpdir:
        request_path = Path(tmpdir) / "request.json"
        agent_path = Path(tmpdir) / "agent.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        agent_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
        request_path.chmod(0o600)
        agent_path.chmod(0o600)
        argv = [
            sys.executable,
            "-m",
            "local_agent.cli",
            "--data-root",
            str(data_root),
            "screenshot",
            "--agent",
            str(agent_path),
            "--request",
            str(request_path),
        ]
        cli_result = await run_cli(argv, harness_root, config.limits.run_timeout_seconds + 30)
        try:
            stdout = cli_result["stdout"].decode("utf-8")
            result = json.loads(stdout)
        except (ValueError, UnicodeDecodeError):
            raise ValueError("Invalid JSON from CLI") from None
        if not isinstance(result, dict) or not isinstance(result.get("run_id"), str):
            raise ValueError("Missing or invalid run_id in CLI output")
        return {
            **result,
            "model": config.model,
            "provider": "ollama",
            "exit_code": cli_result["exit_code"],
        }
