"""Execute the result-location widget with a minimal DOM and both clipboard paths."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_workspace_results_widget():
    gjs = shutil.which("gjs")
    if gjs is None:
        pytest.skip("requires GJS for browser widget execution")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [gjs, str(root / "tests/fixtures/workspace_results_check.js"),
         str(root / "src/local_agent/mobile/static/workspace-results.js")],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks passed" in result.stdout
