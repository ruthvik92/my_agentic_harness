"""Saved reviews start local repairs without client-supplied paths or findings."""

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_workspace_review import candidate  # noqa: F401

from local_agent.config import load_config
from local_agent.mobile.repair_controls import submit_review_repair
from local_agent.mobile.threads import Threads
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces


@pytest.fixture
def repair_server(candidate):  # noqa: F811 -- imported pytest fixture
    root, repository, project, reviewed = candidate
    threads = Threads(root)
    tid = threads.create("Repair review")
    source_id, review_id = "a" * 32, "b" * 32
    record = GitWorktrees(Workspaces(root)).public(reviewed["workspace_id"])
    report = {
        "status": "changes_requested",
        "target": reviewed,
        "verdict": {"summary": "CRLF characters are lost; preserve original newlines."},
        "test_command": "auto",
        "reviewer_run_id": "run_reviewer",
        "checks_run_id": "run_checks",
        "checks": [
            {
                "status": "failed",
                "exit_code": 1,
                "output": "test_crlf: expected 6 characters, got 4",
            }
        ],
        "project_tests": {"status": "test_failed"},
    }
    jobs = {
        source_id: {
            "job_id": source_id,
            "thread_id": tid,
            "status": "completed",
            "mode": "coding",
            "run_id": reviewed["source_run_id"],
            "git_workspace": record,
            "question": "Implement text statistics",
        },
        review_id: {
            "job_id": review_id,
            "thread_id": tid,
            "status": "completed",
            "kind": "workspace_review",
            "workspace_review": report,
        },
    }
    threads.add_exchange(
        tid, "Implement", "Candidate", source_id, reviewed["source_run_id"], "local"
    )
    threads.add_exchange(tid, "Review", "Review findings", review_id, "run_reviewer", "reviewer")
    # The report is older than the normal three-exchange context window.
    for n in range(4):
        threads.add_exchange(tid, "other question", "other answer", f"{n:032x}", None, "local")
    thread = threads.get(tid)
    thread["image"] = "old image must not be reused"
    threads.update(tid, image=thread["image"])
    captured = []

    def submit(request, *, config, metadata):
        captured.append((copy.deepcopy(request), config, copy.deepcopy(metadata)))
        job_id = "c" * 32
        jobs[job_id] = {"job_id": job_id, "status": "queued", **metadata}
        return job_id

    cfg = load_config(Path("config/coder.yaml")).model_copy(update={"project_tests": False})
    server = SimpleNamespace(
        root=root,
        threads=threads,
        allowed_roots=[repository],
        default_profile="coder.yaml",
        jobs=SimpleNamespace(get=lambda job_id: jobs.get(job_id), submit=submit),
        profiles=SimpleNamespace(load=lambda name: cfg),
        models=SimpleNamespace(verifier_path=None),
        usage_baseline=lambda: "local",
    )
    payload = {
        "review_job_id": review_id,
        "candidate_commit": reviewed["candidate_commit"],
        "profile_name": "coder.yaml",
    }
    return server, tid, payload, jobs, captured, report, project


def test_repair_uses_saved_target_and_evidence_outside_history(repair_server):
    server, tid, payload, _, captured, report, _ = repair_server
    assert "CRLF" not in str(server.threads.history(tid))
    job_id = submit_review_repair(server, tid, payload)
    request, cfg, metadata = captured[0]
    assert request["workspace"] == report["target"]["repository"]
    assert request["continue_workspace_id"] == report["target"]["workspace_id"]
    assert request["working_directory"] == report["target"]["working_directory"]
    assert "CRLF" in request["question"] and "expected 6 characters, got 4" in request["question"]
    assert len(request["question"]) <= 8000
    assert "image" not in request
    assert cfg.provider == "ollama" and cfg.project_tests
    assert metadata["repair_review_job_id"] == payload["review_job_id"]
    assert {"run_reviewer", "run_checks", report["target"]["source_run_id"]} <= set(
        metadata["source_run_ids"]
    )
    assert request["repair_context"]["target"] == report["target"]
    assert server.threads.get(tid)["pending_job"] == job_id
    with pytest.raises(ValueError, match="pending"):
        submit_review_repair(server, tid, payload)
    assert len(captured) == 1


@pytest.mark.parametrize(
    "change",
    [
        "foreign_review",
        "foreign_source",
        "missing_source",
        "missing_message",
        "approved",
        "merged",
        "merging",
        "pending",
        "commit",
        "dirty",
        "newer_run",
        "paid",
        "chat",
        "client_path",
        "client_findings",
        "paid_override",
    ],
)
def test_repair_rejects_invalid_or_stale_selection(repair_server, change):
    server, tid, payload, jobs, captured, report, project = repair_server
    if change == "foreign_review":
        jobs[payload["review_job_id"]]["thread_id"] = "d" * 32
    elif change == "foreign_source":
        jobs["a" * 32]["thread_id"] = "d" * 32
    elif change == "missing_source":
        del jobs["a" * 32]
    elif change == "missing_message":
        thread = server.threads.get(tid)
        server.threads.update(
            tid,
            messages=[m for m in thread["messages"] if m.get("job_id") != payload["review_job_id"]],
        )
    elif change == "approved":
        report["status"] = "approved"
    elif change in {"merged", "merging"}:
        report["merge"] = {"status": change}
    elif change == "pending":
        jobs["e" * 32] = {"status": "running"}
        server.threads.update(tid, pending_job="e" * 32)
    elif change == "commit":
        payload["candidate_commit"] = "0" * 40
    elif change == "dirty":
        (project / "value.py").write_text("VALUE = 99\n")
    elif change == "newer_run":
        manager = GitWorktrees(Workspaces(server.root))
        record = manager.load(report["target"]["workspace_id"])
        record["run_id"] = "run_newer"
        manager.save(record)
    elif change in {"paid", "chat"}:
        cfg = load_config(
            Path("config/coder.yaml") if change == "paid" else Path("config/browser.yaml")
        )
        if change == "paid":
            cfg = cfg.model_copy(update={"provider": "openai"})
        server.profiles.load = lambda _: cfg
    elif change == "client_path":
        payload["workspace"] = "/untrusted"
    elif change == "client_findings":
        payload["question"] = "Discard the saved review"
    elif change == "paid_override":
        payload["model_id"] = "openai:gpt-6.1-sol"
    with pytest.raises((ValueError, RuntimeError)):
        submit_review_repair(server, tid, payload)
    assert not captured


def test_failed_inspection_can_be_repaired_and_evidence_is_bounded(repair_server):
    server, tid, payload, jobs, captured, report, _ = repair_server
    jobs[payload["review_job_id"]]["status"] = "failed"
    report["status"] = "failed"
    report["project_tests"] = {"status": "environment_blocked", "error": "Dependency unavailable"}
    report["checks"][0]["output"] += "\nx" * 100000
    submit_review_repair(server, tid, payload)
    request = captured[0][0]
    assert len(request["question"]) <= 8000
    assert "Dependency unavailable" in request["question"]
    assert "truncated" in request["question"]
    assert "expected 6 characters" in request["question"]


def test_local_model_override_and_persistent_mode_are_preserved(repair_server, monkeypatch):
    from local_agent.mobile.models import Models

    server, tid, payload, _, captured, _, _ = repair_server
    monkeypatch.setattr(
        Models,
        "catalog",
        lambda *_: {
            "models": [
                {
                    "id": "ollama:chosen-local",
                    "provider": "ollama",
                    "model": "chosen-local",
                    "selectable": True,
                    "vision": False,
                }
            ]
        },
    )
    submit_review_repair(
        server, tid, {**payload, "model_id": "ollama:chosen-local", "execution_mode": "persistent"}
    )
    _, cfg, metadata = captured[0]
    assert cfg.model == "chosen-local"
    assert cfg.execution.execution_mode_default == metadata["execution_mode"] == "persistent"
    assert (
        metadata["question"] == "Fix the findings from this workspace review and rerun the tests."
    )


def test_controller_repair_request_survives_cli_normalization(repair_server, monkeypatch, tmp_path):
    import json

    from local_agent.cli import main

    server, tid, payload, _, captured, _, _ = repair_server
    submit_review_repair(server, tid, payload)
    task, cfg, _ = captured[0]
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(task))
    config_path = tmp_path / "config.json"
    config_path.write_text(cfg.model_dump_json())
    received = []

    async def run_browser(store, config, request, sandbox, **kwargs):
        received.append(request)
        return {"status": "completed_unverified", "audit": {"ok": True}}

    monkeypatch.setattr("local_agent.mobile.browser_runtime.run_browser", run_browser)
    assert (
        main(
            [
                "--data-root",
                str(server.root),
                "browser-run",
                "--agent",
                str(config_path),
                "--request",
                str(request_path),
                "--allow-root",
                task["workspace"],
            ]
        )
        == 0
    )
    assert received[0]["repair_context"] == task["repair_context"]


def test_repair_http_requires_auth_and_uses_saved_report(repair_server):
    import threading

    import httpx
    from test_mobile_web import login

    from local_agent.mobile.web import BrowserServer

    fake, tid, payload, _, captured, _, _ = repair_server
    server = BrowserServer(
        fake.root, Path("config/browser.yaml"), port=0, allowed_roots=fake.allowed_roots
    )
    server.jobs.close()
    fake.jobs.close = lambda: None
    server.jobs, server.threads, server.profiles = fake.jobs, fake.threads, fake.profiles
    worker = threading.Thread(target=server.serve_forever)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    route = f"/api/threads/{tid}/repair-review"
    try:
        with httpx.Client(base_url=url, headers={"Origin": url}, trust_env=False) as client:
            assert client.post(route, json=payload).status_code == 401
            login(server, client)
            assert (
                client.post(route, json=payload, headers={"Origin": "http://elsewhere"}).status_code
                == 403
            )
            assert client.post(route, json={**payload, "workspace": "/forged"}).status_code == 400
            response = client.post(route, json=payload)
            assert response.status_code == 202, response.text
            assert response.json()["job_id"] == "c" * 32
            assert len(captured) == 1
            assert client.post(route, json=payload).status_code == 400
            assert len(captured) == 1
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def runtime_request(repair_server):
    """Give the candidate a real terminal source run, as browser coding does."""
    import asyncio

    from local_agent.runtime.loop import simulate
    from local_agent.storage.database import Store

    server, tid, payload, jobs, captured, report, _ = repair_server
    store = Store(server.root)
    run_id = asyncio.run(simulate(store))["run_id"]
    manager = GitWorktrees(Workspaces(server.root))
    record = manager.load(report["target"]["workspace_id"])
    record["run_id"] = run_id
    manager.save(record)
    report["target"]["source_run_id"] = run_id
    jobs["a" * 32]["run_id"] = run_id
    submit_review_repair(server, tid, payload)
    request, cfg, _ = captured[0]
    return store, request, cfg


def test_queued_repair_rechecks_workspace_before_continuing(repair_server):
    import asyncio

    from local_agent.doctor import sandbox_config
    from local_agent.mobile.browser_runtime import run_browser
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.runtime.loop import simulate

    store, request, cfg = runtime_request(repair_server)
    try:
        manager = GitWorktrees(Workspaces(store.root))
        record = manager.load(request["continue_workspace_id"])
        newer = asyncio.run(simulate(store))["run_id"]
        record["run_id"] = newer
        manager.save(record)
        result = asyncio.run(
            run_browser(store, cfg, request, sandbox_config(), provider=ScriptedProvider([]))
        )
        assert result["status"] == "failed", result
        assert "newer task" in result["error"]
        assert manager.load(record["workspace_id"])["run_id"] == newer
    finally:
        store.close()


def test_repair_runs_in_same_workspace_with_evidence_and_independent_checks(repair_server, request):
    import asyncio
    import json

    from local_agent.doctor import sandbox_config
    from local_agent.mobile.browser_runtime import run_browser
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.observability.audit import audit

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store, task, cfg = runtime_request(repair_server)
    script = ScriptedProvider(
        [
            {
                "text": "Read retained findings and repair",
                "finish_status": "tool_calls",
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "scratch/repair-review.json"}},
                    {
                        "name": "run_command",
                        "arguments": {
                            "argv": [
                                "python",
                                "-c",
                                "from pathlib import Path; Path('value.py').write_text('VALUE = 3\\n'); "
                                "Path('test_value.py').write_text('from value import VALUE\\ndef test_value():\\n    assert VALUE == 3\\n')",
                            ]
                        },
                    },
                ],
            },
            {
                "text": "Repair ready for independent checks",
                "finish_status": "stop",
                "tool_calls": [],
            },
        ]
    )
    try:
        result = asyncio.run(
            run_browser(store, cfg, task, {**sandbox_config(), "image": image}, provider=script)
        )
        assert result["status"] == "completed_unverified", result
        assert result["workspace_id"] == task["continue_workspace_id"]
        assert result["project_tests"]["status"] == "passed"
        assert (Path(task["workspace"]) / "value.py").read_text() == "VALUE = 1\n"
        evidence = json.loads(
            (Path(result["workspace"]) / "scratch/repair-review.json").read_text()
        )
        assert evidence["evidence"]["checks"][0]["output"].startswith("test_crlf")
        assert (
            result["git_workspace"]["candidate_commit"]
            != task["repair_context"]["target"]["candidate_commit"]
        )
        assert audit(store, result["run_id"])["ok"]
    finally:
        store.close()


def test_repeated_edit_failure_names_the_tool_file_and_cause(repair_server, request):
    import asyncio

    from local_agent.doctor import sandbox_config
    from local_agent.mobile.browser_runtime import run_browser
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.storage.blobs import digest

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store, task, cfg = runtime_request(repair_server)
    arguments = {
        "path": "project/value.py",
        "old_text": "does not exist in the file",
        "new_text": "VALUE = 3\n",
        "expected_hash": digest(b"VALUE = 2\n"),
    }
    script = ScriptedProvider(
        [
            {
                "text": "Patch",
                "finish_status": "tool_calls",
                "tool_calls": [{"name": "patch_file", "arguments": arguments}],
            }
            for _ in range(3)
        ]
    )
    try:
        result = asyncio.run(
            run_browser(store, cfg, task, {**sandbox_config(), "image": image}, provider=script)
        )
        assert result["status"] == "budget_exhausted", result
        assert "patch_file for project/value.py" in result["error"]
        assert "patch requires one exact match" in result["error"]
    finally:
        store.close()
