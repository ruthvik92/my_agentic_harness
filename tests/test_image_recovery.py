import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.runtime.image_records import tool_images
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store


@pytest.mark.parametrize("point", ["after_result_publication", "after_result_commit"])
def test_image_survives_crash_after_result(tmp_path, request, point):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root = tmp_path / "data"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "image_crash_driver.py"), str(root), point, image],
        timeout=60,
        check=False,
    )
    assert result.returncode == 86
    store = Store(root)
    run_id = store.db.execute("SELECT id FROM runs").fetchone()[0]
    config = load_config(Path("config/coder.yaml"))
    config = config.model_copy(
        update={"tools": tuple(dict.fromkeys((*config.tools, "view_image")))}
    )
    provider = ScriptedProvider(
        responses=({"text": "Done", "tool_calls": [], "finish_status": "stop"},)
    )
    agent = Agent(
        store,
        config,
        {**sandbox_config(), "image": image},
        provider=provider,
    )
    manifest = store.blobs.json(store.run(run_id)["manifest_ref"])
    workspace = root / "sandboxes" / manifest["workspace_id"] / "project" / "visible.png"
    original = workspace.read_bytes()
    if point == "after_result_commit":
        workspace.unlink()
    resumed = asyncio.run(agent.run(None, "", resume_run_id=run_id))
    assert resumed["status"] == "completed_unverified", resumed
    assert audit(store, run_id)["ok"]
    images = tool_images(store, run_id)
    assert len(images) == 1, images
    assert store.blobs.read(images[0]["image_ref"]) == original
    snapshot = store.blobs.json(provider.requests[0].context_ref)
    messages = store.blobs.json(snapshot["payload_ref"])["messages"]
    user_images = [m for m in messages if m["role"] == "user" and m.get("images")]
    assert user_images, messages
    first_image = next(i for i, m in enumerate(messages) if m.get("images"))
    assert all(i < first_image for i, m in enumerate(messages) if m["role"] == "tool")
    attempts = store.db.execute(
        "SELECT request_ref FROM execution_attempts"
    ).fetchall()
    view_rows = [
        row for row in attempts if store.blobs.json(row["request_ref"])["tool"] == "view_image"
    ]
    assert len(view_rows) == 1, view_rows
    assert store.db.execute(
        "SELECT state FROM execution_attempts WHERE request_ref=?",
        (view_rows[0]["request_ref"],),
    ).fetchone()["state"] == "finished"
    refs, _ = roots(store, run_id)
    assert images[0]["image_ref"] in refs
    assert images[0]["attachment_ref"] in refs
    store.close()
