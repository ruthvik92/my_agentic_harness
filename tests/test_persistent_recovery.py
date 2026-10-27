import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.contracts import ExecutionSettings
from local_agent.doctor import sandbox_config
from local_agent.executor.maintenance import sweep
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.storage.database import Store


@pytest.mark.parametrize("point", [
    "after_container_launch", "after_result_publication", "after_result_commit",
])
def test_persistent_controller_crash_never_replays_mutation(tmp_path, request, point):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root = tmp_path / "data"
    child = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("crash_driver.py")),
         str(root), point, image, "persistent"],
        timeout=60, check=False,
    )
    assert child.returncode == 86
    store = Store(root)
    try:
        row = store.db.execute(
            "SELECT id,manifest_ref FROM runs WHERE status='running' ORDER BY created_utc LIMIT 1"
        ).fetchone()
        run_id = row["id"]
        manifest = store.blobs.json(row["manifest_ref"])
        provider = ScriptedProvider(responses=(
            {"text": "Done", "tool_calls": [], "finish_status": "stop"},
        ))
        config = load_config(Path("config/coder.yaml")).model_copy(update={
            "execution": ExecutionSettings(execution_mode_default="persistent"),
        })
        agent = Agent(store, config, {**sandbox_config(), "image": image}, provider=provider)
        resumed = asyncio.run(agent.run(None, "", resume_run_id=run_id))
        count = root / "sandboxes" / manifest["workspace_id"] / "project/count"
        assert not count.exists() or count.read_text() == "X"
        if point == "after_container_launch":
            assert resumed["status"] == "needs_reconciliation", resumed
            assert not provider.requests
        else:
            assert resumed["status"] == "completed_unverified", resumed
            assert count.read_text() == "X"
            report = audit(store, run_id)
            assert report["ok"], report["errors"]
    finally:
        try:
            if "manifest" in locals():
                asyncio.run(sweep(
                    root, image, ExecutionSettings(), workspace_id=manifest["workspace_id"]
                ))
        finally:
            store.close()
