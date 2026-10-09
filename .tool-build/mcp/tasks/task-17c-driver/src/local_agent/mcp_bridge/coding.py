import json
import sys
import tempfile
from pathlib import Path

from local_agent.contracts import AgentConfig

from .process import run_cli


async def run_code(
    repo: Path, task: str, config: AgentConfig, data_root: Path, harness_root: Path
) -> dict:
    if not task or len(task) > 16000:
        raise ValueError("Task must be non-empty and <= 16000 characters")
    if not repo.is_dir():
        raise ValueError("Repo must be a resolved directory")
    if config.provider != "ollama":
        raise ValueError("Provider must be 'ollama'")
    data_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mcp-code-", dir=data_root) as tmpdir:
        task_path = Path(tmpdir) / "task.txt"
        agent_path = Path(tmpdir) / "agent.json"

        task_path.write_text(task, encoding="utf-8")
        task_path.chmod(0o600)

        agent_path.write_text(json.dumps(config.model_dump(mode="json")))
        agent_path.chmod(0o600)

        argv = [
            sys.executable,
            "-m",
            "local_agent.cli",
            "--data-root",
            str(data_root),
            "run",
            "--agent",
            str(agent_path),
            "--repo",
            str(repo),
            "--task-file",
            str(task_path),
        ]

        cli_result = await run_cli(argv, harness_root, config.limits.run_timeout_seconds + 30)

        try:
            output = json.loads(cli_result["stdout"].decode("utf-8"))
        except Exception:
            raise ValueError("Harness returned invalid JSON") from None

        if (
            not isinstance(output, dict)
            or "run_id" not in output
            or not isinstance(output["run_id"], str)
        ):
            raise ValueError("Harness result missing run_id")

        result = dict(output)
        result["provider"] = config.provider
        result["model"] = config.model
        result["exit_code"] = cli_result["exit_code"]
        return result
