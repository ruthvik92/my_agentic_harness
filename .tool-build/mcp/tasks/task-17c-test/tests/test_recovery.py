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
from local_agent.runtime.replay import recorded_replay
from local_agent.storage.database import Store
from local_agent.storage.locks import run_lock


@pytest.mark.parametrize(
    "point",
    [
        "after_model_request",
        "after_response_persistence",
        "after_dispatch_intent",
        "after_container_launch",
        "after_result_publication",
        "after_result_commit",
    ],
)
def test_real_controller_crashes_never_replay_uncertain_mutations(tmp_path, request, point):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root = tmp_path / "data"
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "crash_driver.py"), str(root), point, image],
        timeout=60,
        check=False,
    )
    assert result.returncode == 86
    store = Store(root)
    run_id = store.db.execute("SELECT id FROM runs").fetchone()[0]
    provider = ScriptedProvider(
        responses=({"text": "Done", "tool_calls": [], "finish_status": "stop"},)
    )
    agent = Agent(
        store,
        load_config(Path("config/coder.yaml")),
        {**sandbox_config(), "image": image},
        provider=provider,
    )
    resumed = asyncio.run(agent.run(None, "", resume_run_id=run_id))
    manifest = store.blobs.json(store.run(run_id)["manifest_ref"])
    count = store.root / "sandboxes" / manifest["workspace_id"] / "project" / "count"
    assert not count.exists() or count.read_text() == "X", "mutation was silently replayed"
    events = store.events(run_id)
    assert any(e.event_type == "run.resumed" for e in events)
    assert len({e.trace_id for e in events}) >= 2
    if point == "after_dispatch_intent":
        assert resumed["status"] == "needs_reconciliation", resumed
        assert not count.exists()
        assert not audit(store, run_id)["ok"]
        assert not provider.requests
    else:
        assert resumed["status"] == "completed_unverified", resumed
        report = audit(store, run_id)
        assert report["ok"], report["errors"]
        replay = recorded_replay(store, run_id)
        assert replay["real_tools_executed"] == 0
        assert not replay["pending_execution_ids"]
    if point in {"after_result_commit", "after_result_publication"}:
        assert count.read_text() == "X"
        external_executions = store.db.execute(
            "SELECT e.id,m.request_ref FROM execution_attempts e JOIN tool_calls t "
            "ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
            (run_id,),
        ).fetchall()
        assert (
            len(
                [
                    row
                    for row in external_executions
                    if store.blobs.json(row["request_ref"])["provider"] == "scripted"
                ]
            )
            == 1
        )
    store.close()


def test_run_lease_excludes_second_controller(tmp_path):
    store = Store(tmp_path / "data")
    with run_lock(store.control):
        with pytest.raises(RuntimeError, match="another coding run"):
            with run_lock(store.control):
                raise AssertionError("second lease acquired")
    with run_lock(store.control):
        pass
    store.close()


@pytest.mark.parametrize("during", ["model", "container"])
def test_cancellation_stops_active_boundary(tmp_path, request, during):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    from local_agent.runtime.cancellation import cancel

    class SlowProvider(ScriptedProvider):
        async def generate(self, request):
            if during == "model":
                await asyncio.sleep(30)
            return await super().generate(request)

    provider = SlowProvider(
        responses=(
            {
                "text": "Wait",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "arguments": {
                            "argv": ["python", "-c", "import time;time.sleep(30)"],
                        },
                    }
                ],
                "finish_status": "tool_calls",
            },
        )
    )
    store = Store(tmp_path / "data")
    source = tmp_path / "repo"
    source.mkdir()
    agent = Agent(
        store,
        load_config(Path("config/coder.yaml")),
        {**sandbox_config(), "image": image},
        provider=provider,
    )

    async def exercise():
        running = asyncio.create_task(agent.run(source, "Wait"))
        for _ in range(200):
            await asyncio.sleep(0.05)
            if not agent.created:
                continue
            events = store.events(agent.run_id)
            if during == "model":
                ready = any(
                    e.event_type == "model.requested"
                    and store.blobs.json(e.data["request_ref"])["provider"] == "scripted"
                    for e in events
                )
            else:
                ready = agent.current_external and any(
                    e.event_type == "execution.started" for e in events
                )
            if ready:
                await cancel(store, agent.run_id)
                break
        else:
            raise AssertionError("boundary not reached")
        return await asyncio.wait_for(running, 15)

    result = asyncio.run(exercise())
    assert result["status"] == "cancelled", result
    report = audit(store, result["run_id"])
    assert report["ok"], report["errors"]
    store.close()
