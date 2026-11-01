"""Execute the result-location widget with a minimal DOM and both clipboard paths."""

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("script,asset", [
    ("workspace_results_check.js", "workspace-results.js"),
    ("config_controls_check.js", "config-controls.js"),
    ("thread_controls_check.js", "thread-controls.js"),
    ("browser_navigation_check.js", "index.html"),
    ("workspace_reviews_check.js", "workspace-reviews.js"),
    ("browser_loop_controls_check.js", "index.html"),
])
def test_workspace_results_widget(script, asset):
    gjs = shutil.which("gjs")
    if gjs is None:
        pytest.skip("requires GJS for browser widget execution")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [gjs, str(root / "tests/fixtures" / script),
         str(root / "src/local_agent/mobile/static" / asset)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks passed" in result.stdout
