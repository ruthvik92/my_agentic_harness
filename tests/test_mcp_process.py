import asyncio
import json
import sys
from pathlib import Path
from typing import Dict

import pytest

from local_agent.mcp_bridge.process import run_cli


def test_stdout_exit_and_secret_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "fake-sentinel-for-test")
    PYTHON_CODE = """
import json
import os
import sys
print(json.dumps({"key": os.environ.get("OPENAI_API_KEY"), "message": "hello"}))
sys.exit(7)
    """
    argv = [sys.executable, "-c", PYTHON_CODE]
    result: Dict[str, bytes] = asyncio.run(run_cli(argv, tmp_path, 5))
    assert result["exit_code"] == 7
    assert result["stderr"] == b""
    assert json.loads(result["stdout"]) == {"key": None, "message": "hello"}
