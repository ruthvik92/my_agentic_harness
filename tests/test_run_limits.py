"""Submission limits are validated without changing profiles, and bound loop stages."""

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_review_repair import repair_server  # noqa: F401
from test_workspace_review import candidate  # noqa: F401

from local_agent.config import load_config
from local_agent.mobile.jobs import Jobs
from local_agent.mobile.profile_turns import submit_profile_turn
from local_agent.mobile.run_limits import override


@pytest.mark.parametrize("minutes", [True, 0, -1, 1441, 1.5, "10"])
def test_runtime_rejects_invalid_overrides(minutes):
    config = load_config(Path("config/coder.yaml"))
    with pytest.raises(ValueError, match="minutes"):
        override(config, minutes)


def test_ordinary_task_runtime_override_and_context_are_persisted(repair_server):  # noqa: F811
    server, tid, _, jobs, captured, report, _ = repair_server
    server.jobs.recent = lambda **_: list(reversed(list(jobs.values())))
    server.threads.update(tid, image=None)
    original = server.profiles.load("coder.yaml")
    payload = {
        "profile_name": "coder.yaml",
        "workspace": report["target"]["repository"],
        "continue_workspace_id": report["target"]["workspace_id"],
        "question": "Continue with the unresolved check",
        "run_limit_minutes": 3,
        "n_last_chats": 2,
    }
    submit_profile_turn(server, tid, payload)
    request, cfg, metadata = captured[-1]
    assert cfg.limits.run_timeout_seconds == 180
    assert original.limits.run_timeout_seconds != 180
    assert metadata["run_timeout_seconds"] == 180
    assert metadata["n_last_chats"] == request["task_context"]["n_last_chats"] == 2
    assert metadata["task_context"] == request["task_context"]
    assert metadata["task_context"]["original_task"] == "Implement text statistics"
    assert override(original, None) is original


@pytest.mark.parametrize("value", [True, 0, 101, "3", 2.5, None])
def test_submission_rejects_invalid_history_limit_before_queueing(repair_server, value):  # noqa: F811
    server, tid, _, _, captured, _, _ = repair_server
    with pytest.raises(ValueError, match="n_last_chats"):
        submit_profile_turn(server, tid, {"profile_name": "coder.yaml", "n_last_chats": value})
    assert not captured


@pytest.mark.parametrize("expired", [False, True])
def test_job_wall_deadline_includes_preflight_and_independent_checks(
    tmp_path, monkeypatch, expired
):
    config = load_config(Path("config/coder.yaml"))
    job_id = "a" * 32
    directory = tmp_path / job_id
    directory.mkdir()
    request = directory / "request.json"
    request.write_text(json.dumps({"mode": "coding", "question": "Test"}))
    request.with_name("config.json").write_text(config.model_dump_json())
    job = Jobs.__new__(Jobs)
    job.root, job.agent_path, job.allowed_roots = tmp_path, Path("config/coder.yaml"), ()
    job.get = lambda _: {"loop_deadline": time.time() + (-1 if expired else 25)}
    timeouts = []

    def run(argv, **kwargs):
        timeouts.append(kwargs["timeout"])
        return SimpleNamespace(stdout='{"status":"failed"}', stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    if expired:
        with pytest.raises(TimeoutError, match="total budget"):
            job.execute(request)
        assert not timeouts
    else:
        job.execute(request)
        assert 0 < timeouts[0] <= 25


def test_restart_interrupts_queued_job_without_running_it(tmp_path):
    from local_agent.mobile.jobs import publish

    directory = tmp_path / "phone/jobs" / ("b" * 32)
    directory.mkdir(parents=True)
    publish(directory / "status.json", {"job_id": "b" * 32, "created": 0, "status": "queued"})
    config = load_config(Path("config/browser.yaml"))
    jobs = Jobs(
        tmp_path,
        Path("config/browser.yaml"),
        config,
        runner=lambda _: pytest.fail("Interrupted job replayed"),
    )
    try:
        assert jobs.get("b" * 32)["status"] == "interrupted"
    finally:
        jobs.close()


def test_expired_check_deadline_prevents_dependency_preparation(tmp_path, monkeypatch):
    import asyncio

    from local_agent.storage.database import Store
    from local_agent.testing.checks import run_checks

    called = []

    async def prepare(*_):
        called.append(True)
        await asyncio.sleep(1)

    monkeypatch.setattr("local_agent.testing.checks.prepare_environment", prepare)
    config = load_config(Path("config/coder.yaml"))
    store = Store(tmp_path / "state")
    try:
        report, result, _ = asyncio.run(
            run_checks(
                store,
                config,
                tmp_path,
                {"commands": []},
                {"image": "sha256:" + "a" * 64},
                deadline=time.monotonic() - 1,
            )
        )
        assert not called
        assert result["status"] == "failed"
        assert report["audit"]["ok"]
        assert "deadline" in report["error"]
    finally:
        store.close()


def test_review_repair_uses_the_runtime_control(repair_server):  # noqa: F811
    from local_agent.mobile.repair_controls import submit_review_repair

    server, tid, payload, _, captured, _, _ = repair_server
    submit_review_repair(server, tid, {**payload, "run_limit_minutes": 2})
    assert captured[-1][1].limits.run_timeout_seconds == 120
