import asyncio
import json
import sys
from pathlib import Path

from local_agent.contracts import AgentConfig
from local_agent.mcp_bridge import coding


def test_run_code(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    data_root = tmp_path / "data"
    cfg = AgentConfig(
        provider="ollama",
        model="local-test",
        instructions_hash="sha256:" + "0" * 64,
    )

    async def fake_run_cli(argv, cwd, timeout):
        assert argv[:12] == [
            sys.executable,
            "-m",
            "local_agent.cli",
            "--data-root",
            str(data_root),
            "run",
            "--agent",
            str(argv[7]),
            "--repo",
            str(argv[9]),
            "--task-file",
            str(argv[11]),
        ]
        assert argv[7] == str(argv[7]) and Path(argv[7]).is_file()
        assert Path(argv[9]) == repo
        cfg_json = json.loads(Path(argv[7]).read_text(encoding="utf-8"))
        assert cfg_json["model"] == "local-test"
        assert cfg_json["provider"] == "ollama"
        assert Path(argv[7]).stat().st_mode & 0o777 == 0o600
        task_path = Path(argv[11])
        assert task_path.stat().st_mode & 0o777 == 0o600
        assert task_path.read_text(encoding="utf-8") == "test task"
        return {
            "stdout": json.dumps(
                {
                    "run_id": "run_fixture",
                    "status": "budget_exhausted",
                    "diff_ref": "blob://fixture",
                }
            ).encode(),
            "stderr": b"",
            "exit_code": 1,
        }

    monkeypatch.setattr(coding, "run_cli", fake_run_cli)
    result = asyncio.run(coding.run_code(repo, "test task", cfg, data_root, tmp_path))
    assert result["status"] == "budget_exhausted"
    assert result["run_id"] == "run_fixture"
    assert result["diff_ref"] == "blob://fixture"
    assert result["exit_code"] == 1
    assert result["provider"] == "ollama"
    assert result["model"] == "local-test"
    assert list(data_root.iterdir()) == []
