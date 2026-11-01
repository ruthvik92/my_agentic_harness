"""Exact-commit workspace inspection, independent checks and host merge boundaries."""

import asyncio
import json
from pathlib import Path

import pytest

from local_agent.config import load_config
from local_agent.doctor import sandbox_config
from local_agent.mobile.models import Models
from local_agent.mobile.workspace_review import run_review
from local_agent.models.scripted import ScriptedProvider
from local_agent.storage.database import Store
from local_agent.workspace.git import GitWorktrees, git
from local_agent.workspace.manager import Workspaces, copy_tree
from local_agent.workspace.review import capture_target, merge_candidate


@pytest.fixture
def candidate(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "value.py").write_text("VALUE = 1\n")
    (repository / "test_value.py").write_text(
        "from value import VALUE\ndef test_value():\n    assert VALUE == 2\n"
    )
    (repository / ".gitignore").write_text("__pycache__/\n.pytest_cache/\nignored/\n")
    git("-C", repository, "init", "-b", "main")
    git("-C", repository, "add", ".")
    git("-C", repository, "commit", "-m", "Initial")
    root = tmp_path / "data"
    workspaces = Workspaces(root)
    ws, workspace = workspaces.create_coding(repository, "run_candidate")
    (workspace / "project/value.py").write_text("VALUE = 2\n")
    (workspace / "project/new.txt").write_text("candidate file")
    snapshot = tmp_path / "snapshot"
    copy_tree(workspace / "project", snapshot, exclude=(".git",))
    manager = GitWorktrees(workspaces)
    record = manager.finalize(ws, snapshot)
    reviewed = capture_target(root, ws, record["candidate_commit"], [repository], ".")
    return root, repository, workspace / "project", reviewed


def review_config(monkeypatch):
    from test_mobile_threads import catalog

    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    models = Models(
        load_config(Path("config/browser.yaml")), "examples/configs/openai-reviewer.yaml"
    )
    return models.select_reviewer("openai:gpt-6-luna", workspace=True)


def provider(*, verdict="approve", inspect=True, mutate=False, tests=None, declared_tests=None,
             inspect_path="project/value.py", findings=None):
    calls = []
    if inspect:
        calls.extend(
            [
                {"name": "read_file", "arguments": {"path": "scratch/review.diff"}},
                {"name": "read_file", "arguments": {"path": inspect_path}},
            ]
        )
    if mutate:
        calls.append(
            {
                "name": "run_command",
                "arguments": {
                    "argv": [
                        "python",
                        "-c",
                        "from pathlib import Path; Path('value.py').write_text('VALUE = 999\\n')",
                    ],
                },
            }
        )
    for test in tests or []:
        calls.append({"name": "run_command", "arguments": test})
    for index, call in enumerate(calls):
        call["provider_id"] = "call_scripted_" + str(index)
    responses = []
    if calls:
        responses.append(
            {"text": "Inspect evidence", "tool_calls": calls, "finish_status": "tool_calls"}
        )
    responses.append(
        {
            "text": json.dumps(
                {"verdict": verdict, "summary": "Inspected candidate and recorded checks.",
                 **({"findings": findings} if findings is not None else {}),
                 **({"tests": declared_tests if declared_tests is not None else tests}
                    if tests is not None or declared_tests is not None else {})}
            ),
            "tool_calls": [],
            "finish_status": "stop",
        }
    )
    return ScriptedProvider(responses)


def test_exact_commit_merge_preserves_source_until_explicit_action(candidate):
    root, repository, project, reviewed = candidate
    assert (repository / "value.py").read_text() == "VALUE = 1\n"
    merged = merge_candidate(root, reviewed, [repository])
    assert merged["commit"] == reviewed["candidate_commit"]
    assert (repository / "value.py").read_text() == "VALUE = 2\n"
    assert (project / "value.py").read_text() == "VALUE = 2\n"
    assert git("-C", repository, "symbolic-ref", "--short", "HEAD").strip() == b"main"


@pytest.mark.parametrize(
    "change",
    [
        "dirty_source",
        "untracked",
        "dirty_candidate",
        "moved_source",
        "branch",
        "filters",
        "index_flag",
        "ignored_collision",
    ],
)
def test_merge_rejects_changed_or_unsafe_checkout(candidate, change):
    root, repository, project, reviewed = candidate
    if change == "dirty_source":
        (repository / "value.py").write_text("keep my edits\n")
    elif change == "untracked":
        (repository / "local.txt").write_text("keep my file")
    elif change == "dirty_candidate":
        (project / "value.py").write_text("pending candidate edits")
    elif change == "moved_source":
        (repository / "new.txt").write_text("source advanced")
        git("-C", repository, "add", ".")
        git("-C", repository, "commit", "-m", "Advance source")
    elif change == "branch":
        git("-C", repository, "switch", "-c", "other")
    elif change == "filters":
        git("-C", repository, "config", "filter.evil.smudge", "touch SHOULD_NOT_RUN")
    elif change == "index_flag":
        git("-C", repository, "update-index", "--assume-unchanged", "value.py")
    elif change == "ignored_collision":
        (repository / ".git/info/exclude").write_text("new.txt\n")
        (repository / "new.txt").write_text("keep this ignored file")
    before = git("-C", repository, "rev-parse", "HEAD")
    with pytest.raises((ValueError, RuntimeError)):
        merge_candidate(root, reviewed, [repository])
    assert git("-C", repository, "rev-parse", "HEAD") == before
    assert not (repository / "SHOULD_NOT_RUN").exists()


@pytest.mark.parametrize(
    "case",
    [
        "approve",
        "failed_check",
        "no_inspection",
        "changes_requested",
        "mutated_review",
        "mutated_check",
        "continued",
    ],
)
def test_workspace_review_executes_real_checks_in_separate_snapshot(
    candidate, monkeypatch, request, case
):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root, repository, project, reviewed = candidate
    if case == "continued":
        manager = GitWorktrees(Workspaces(root))
        manager.continue_task(reviewed["workspace_id"], repository, "run_followup")
        snapshot = root.parent / "continued-snapshot"
        copy_tree(project, snapshot, exclude=(".git",))
        manager.finalize(reviewed["workspace_id"], snapshot)
        reviewed = capture_target(
            root, reviewed["workspace_id"], reviewed["candidate_commit"], [repository], "."
        )
        assert reviewed["base_commit"] == reviewed["candidate_commit"]
        assert reviewed["diff_base_commit"] == reviewed["source_head"]
    config = review_config(monkeypatch)
    store = Store(root)
    try:
        command = (
            "python -m pytest -q" if case != "failed_check" else "python -c 'raise SystemExit(7)'"
        )
        if case == "mutated_check":
            command = (
                "python -c \"from pathlib import Path; Path('value.py').write_text('VALUE = 3')\""
            )
        result = asyncio.run(
            run_review(
                store,
                config,
                {"review_target": reviewed, "test_command": command, "context": "Fix VALUE"},
                {**sandbox_config(), "image": image},
                [repository],
                provider=provider(
                    inspect=case != "no_inspection",
                    mutate=case == "mutated_review",
                    verdict="request_changes" if case == "changes_requested" else "approve",
                ),
            )
        )
        report = result["workspace_review"]
        assert report["status"] == (
            "approved" if case in {"approve", "continued"} else "changes_requested"
        )
        assert report["checks"][0]["exit_code"] == (7 if case == "failed_check" else 0)
        assert report["audit"]["ok"] and report["checks_audit"]["ok"]
        if case == "continued":
            diff_read = next(
                item
                for item in report["observations"]
                if item["arguments"].get("path") == "scratch/review.diff"
            )
            assert "VALUE = 2" in diff_read["output"]
        assert report["target"]["candidate_commit"] == reviewed["candidate_commit"]
        assert report["review_copy_unchanged"] is (case != "mutated_review")
        assert (repository / "value.py").read_text() == "VALUE = 1\n"
        assert (project / "value.py").read_text() == "VALUE = 2\n"
        assert (
            git("-C", repository, "rev-parse", "HEAD").decode().strip() == reviewed["source_head"]
        )
    finally:
        store.close()


def test_review_rejects_stale_commit_and_roots(candidate):
    root, repository, project, reviewed = candidate
    with pytest.raises(ValueError, match="Candidate changed"):
        capture_target(root, reviewed["workspace_id"], reviewed["base_commit"], [repository], ".")
    with pytest.raises(ValueError, match="outside"):
        capture_target(root, reviewed["workspace_id"], reviewed["candidate_commit"], [project], ".")
    with pytest.raises(ValueError, match="untracked|symlinks"):
        (project / "linked").symlink_to(repository, target_is_directory=True)
        capture_target(
            root, reviewed["workspace_id"], reviewed["candidate_commit"], [repository], "linked"
        )


def test_merge_disables_host_hooks(candidate, tmp_path):
    root, repository, _, reviewed = candidate
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    marker = tmp_path / "executed"
    hook = hooks / "post-merge"
    hook.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\n")
    hook.chmod(0o700)
    git("-C", repository, "config", "core.hooksPath", str(hooks))
    merge_candidate(root, reviewed, [repository])
    assert not marker.exists()


def test_review_queue_report_and_explicit_merge_api(candidate, monkeypatch, request):
    import secrets
    import threading

    import httpx
    from test_mobile_threads import catalog
    from test_mobile_web import login

    from local_agent.mobile.jobs import publish
    from local_agent.mobile.web import BrowserServer

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root, repository, _, reviewed = candidate
    monkeypatch.setenv("OPENAI_API_KEY", "fake-private-key")
    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    captured = []

    def runner(path):
        captured.append(json.loads(path.read_text()))
        store = Store(root)
        try:
            return asyncio.run(
                run_review(
                    store,
                    load_config(path.with_name("config.json")),
                    captured[-1],
                    {**sandbox_config(), "image": image},
                    [repository],
                    provider=provider(),
                )
            )
        finally:
            store.close()

    server = BrowserServer(
        root,
        Path("config/browser.yaml"),
        port=0,
        runner=runner,
        verifier_path="examples/configs/openai-reviewer.yaml",
        allowed_roots=[repository],
    )
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(
            base_url=url, headers={"Origin": url}, trust_env=False, timeout=15
        ) as client:
            tid = server.threads.create("Fix VALUE")
            source_job = secrets.token_hex(16)
            location = server.jobs.directory / source_job
            location.mkdir(mode=0o700)
            record = GitWorktrees(Workspaces(root)).public(reviewed["workspace_id"])
            publish(
                location / "status.json",
                {
                    "job_id": source_job,
                    "thread_id": tid,
                    "status": "completed",
                    "created": 0,
                    "run_id": reviewed["source_run_id"],
                    "mode": "coding",
                    "question": "Fix VALUE",
                    "git_workspace": record,
                    "token_usage": {},
                    "answer": "Done",
                    "model": "local",
                },
            )
            original_job = secrets.token_hex(16)
            original_location = server.jobs.directory / original_job
            original_location.mkdir(mode=0o700)
            publish(
                original_location / "status.json",
                {
                    "job_id": original_job,
                    "thread_id": tid,
                    "status": "completed",
                    "created": -1,
                    "run_id": None,
                    "mode": "coding",
                    "question": "Original task: fix VALUE with regression coverage",
                    "git_workspace": record,
                    "token_usage": {},
                    "answer": "Initial implementation",
                    "model": "local",
                },
            )
            server.threads.add_exchange(
                tid, "Original task", "Initial implementation", original_job, None, "local"
            )
            current = server.jobs.get(source_job)
            current["question"] = "Where are the test files?"
            publish(location / "status.json", current)
            server.threads.add_exchange(
                tid, "Where are the test files?", "Done", source_job, None, "local"
            )
            payload = {
                "answer_job_id": source_job,
                "candidate_commit": reviewed["candidate_commit"],
                "model_id": "openai:gpt-6-luna",
                "test_command": "python -m pytest -q",
                "working_directory": ".",
            }
            endpoint = f"/api/threads/{tid}/workspace-review"
            assert client.post(endpoint, json=payload).status_code == 401
            login(server, client)
            wrong_thread = server.threads.create("Other chat")
            assert (
                client.post(
                    f"/api/threads/{wrong_thread}/workspace-review", json=payload
                ).status_code
                == 400
            )
            assert not captured
            response = client.post(endpoint, json=payload)
            assert response.status_code == 202, response.text
            job_id = response.json()["job_id"]
            # Real Docker takes longer than the generic browser test helper's 5-second deadline.
            import time

            for _ in range(200):
                job = client.get(f"/api/jobs/{job_id}").json()
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(0.05)
            assert job["status"] == "completed", job
            assert "Original task: fix VALUE with regression coverage" in captured[0]["context"]
            assert "Where are the test files?" in captured[0]["context"]
            report = client.get(f"/api/jobs/{job_id}/workspace-review").json()
            assert report["status"] == "approved", report
            assert report["checks"][0]["exit_code"] == 0
            assert "1 passed" in report["checks"][0]["output"]
            assert (repository / "value.py").read_text() == "VALUE = 1\n"
            saved = client.get(f"/api/threads/{tid}").json()
            assert saved["messages"][-1]["workspace_review"]["target"] == report["target"]
            merge = {"review_job_id": job_id, "candidate_commit": reviewed["candidate_commit"]}
            assert (
                client.post(f"/api/threads/{wrong_thread}/merge-review", json=merge).status_code
                == 400
            )
            bad_commit = {**merge, "candidate_commit": reviewed["base_commit"]}
            assert (
                client.post(f"/api/threads/{tid}/merge-review", json=bad_commit).status_code == 400
            )
            saved_job = server.jobs.get(job_id)
            saved_job["workspace_review"]["status"] = "changes_requested"
            publish(server.jobs.directory / job_id / "status.json", saved_job)
            assert client.post(f"/api/threads/{tid}/merge-review", json=merge).status_code == 400
            assert (repository / "value.py").read_text() == "VALUE = 1\n"
            saved_job["workspace_review"]["status"] = "approved"
            publish(server.jobs.directory / job_id / "status.json", saved_job)
            merged = client.post(f"/api/threads/{tid}/merge-review", json=merge)
            assert merged.status_code == 200, merged.text
            assert merged.json()["commit"] == reviewed["candidate_commit"]
            assert (repository / "value.py").read_text() == "VALUE = 2\n"
            assert (
                client.post(f"/api/threads/{tid}/merge-review", json=merge).json() == merged.json()
            )
            assert (
                client.get(f"/api/jobs/{job_id}/workspace-review").json()["merge"]["status"]
                == "merged"
            )
            # Simulate a crash after Git succeeded but before its outcome was published.
            saved_job = server.jobs.get(job_id)
            saved_job["workspace_review"]["merge"] = {"status": "merging"}
            publish(server.jobs.directory / job_id / "status.json", saved_job)
            recovered = client.post(f"/api/threads/{tid}/merge-review", json=merge)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["reconciled"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    def no_replay(path):
        pytest.fail("Restart must not replay a paid review")

    restarted = BrowserServer(
        root,
        Path("config/browser.yaml"),
        port=0,
        runner=no_replay,
        verifier_path="examples/configs/openai-reviewer.yaml",
        allowed_roots=[repository],
    )
    try:
        report = restarted.jobs.get(job_id)["workspace_review"]
        assert report["merge"]["status"] == "merged"
        assert restarted.thread_view(tid)["messages"][-1]["workspace_review"] == report
        assert (
            json.loads((restarted.jobs.directory / job_id / "workspace-review.json").read_text())
            == report
        )
    finally:
        restarted.server_close()


def test_auto_review_runs_new_tests_hidden_by_pytest_defaults(candidate, monkeypatch, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root, repository, project, reviewed = candidate
    manager = GitWorktrees(Workspaces(root))
    manager.continue_task(reviewed["workspace_id"], repository, "run_hidden_test")
    (project / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nnorecursedirs=["fixtures"]\n'
    )
    (project / "fixtures").mkdir()
    (project / "fixtures/test_hidden.py").write_text("def test_hidden():\n assert False\n")
    snapshot = root.parent / "hidden-snapshot"
    copy_tree(project, snapshot, exclude=(".git",))
    published = manager.finalize(reviewed["workspace_id"], snapshot)
    reviewed = capture_target(
        root, reviewed["workspace_id"], published["candidate_commit"], [repository], "."
    )
    store = Store(root)
    try:
        result = asyncio.run(
            run_review(
                store,
                review_config(monkeypatch),
                {"review_target": reviewed, "test_command": "auto"},
                {**sandbox_config(), "image": image},
                [repository],
                provider=provider(),
            )
        )
        report = result["workspace_review"]
        assert report["status"] == "changes_requested"
        assert len(report["checks"]) == 2
        assert report["checks"][0]["exit_code"] == 0
        assert report["checks"][1]["exit_code"] == 1
        assert "fixtures/test_hidden.py" in report["checks"][1]["argv"]
    finally:
        store.close()


@pytest.mark.parametrize("case", ["mixed", "js_only", "no_plan", "failed_js", "no_selection",
                                  "invented", "environment_blocked", "replay_failed"])
def test_auto_reviewer_discovers_tests_and_replays_from_clean_candidate(
    candidate, monkeypatch, request, case
):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image with Node installed")
    root, repository, project, reviewed = candidate
    manager = GitWorktrees(Workspaces(root))
    manager.continue_task(reviewed["workspace_id"], repository, "run_mixed_tests")
    (project / "tests").mkdir()
    (project / "game.js").write_text("module.exports = 2;\n")
    (project / "tests/test_leaderboard.js").write_text(
        "require('assert').strictEqual(require('../game.js'), "
        + ("3" if case == "failed_js" else "2") + ");\n"
    )
    if case in {"js_only", "no_plan"}:
        (project / "value.py").unlink()
        (project / "test_value.py").unlink()
    if case == "no_plan":
        (project / "tests/test_leaderboard.js").rename(project / "test_leaderboard.js")
        (project / "tests").rmdir()
        (project / "test_leaderboard.js").write_text(
            "require('assert').strictEqual(require('./game.js'), 2);\n"
        )
    if case == "environment_blocked":
        (project / "pyproject.toml").write_text(
            '[project]\nname="unprepared"\nversion="1"\ndependencies=["missing-package"]\n'
        )
    snapshot = root.parent / "mixed-snapshot"
    copy_tree(project, snapshot, exclude=(".git",))
    published = manager.finalize(reviewed["workspace_id"], snapshot)
    reviewed = capture_target(
        root, reviewed["workspace_id"], published["candidate_commit"], [repository], "."
    )
    commands = [{"argv": ["node", "tests/test_leaderboard.js"], "cwd": "project"}]
    if case == "no_plan":
        commands[0]["argv"] = ["node", "test_leaderboard.js"]
    if case not in {"js_only", "no_plan"}:
        commands.insert(0, {"argv": ["python", "-m", "pytest", "-q"], "cwd": "project"})
    declared = commands if case == "invented" else None
    if case == "replay_failed":
        check = {"argv": ["python", "-c",
                          "from pathlib import Path; assert Path('/workspace/scratch/reviewer-only').exists()"],
                 "cwd": "project"}
        commands = [{"argv": ["python", "-c",
                              "from pathlib import Path; Path('/workspace/scratch/reviewer-only').touch()"],
                     "cwd": "project"}, check]
        declared = [check]
    store = Store(root)
    try:
        result = asyncio.run(run_review(
            store, review_config(monkeypatch),
            {"review_target": reviewed, "test_command": "auto", "context": "Review the game"},
            {**sandbox_config(), "image": image}, [repository],
            provider=provider(
                tests=[] if case in {"no_selection", "invented", "environment_blocked"}
                else commands,
                declared_tests=declared,
                inspect_path="project/game.js",
            ),
        ))
        report = result["workspace_review"]
        assert report["status"] == ("approved" if case in {"mixed", "js_only", "no_plan"}
                                    else "changes_requested")
        if case in {"mixed", "js_only", "no_plan"}:
            assert report["reviewer_tests"]["status"] == "passed"
            assert report["checks_passed"] and report["checks_audit"]["ok"]
            assert len(report["checks_run_ids"]) == 2
            assert {tuple(item["argv"]) for item in report["checks"]
                    if item.get("source") == "reviewer_discovery"} == {
                        tuple(command["argv"]) for command in commands
                    }
            assert report["checks_copy_unchanged"] and report["review_copy_unchanged"]
        elif case == "replay_failed":
            assert report["reviewer_tests"]["status"] == "test_failed"
            assert not report["checks_passed"]
        else:
            assert report["test_discovery_error"]
            assert not report["checks_passed"]
        if case == "environment_blocked":
            assert report["project_tests"]["status"] == "environment_blocked"
            assert report["reviewer_run_id"]
            assert report["inspected_files_and_diff"]
        assert (repository / "value.py").read_text() == "VALUE = 1\n"
        assert git("-C", repository, "rev-parse", "HEAD").decode().strip() == reviewed["source_head"]
    finally:
        store.close()


@pytest.mark.parametrize('finish_reason', ['tool_budget', 'model_turns', 'repeated_work'])
def test_review_reserves_report_turn_and_final_diff(candidate, monkeypatch, request, finish_reason):
    from local_agent.mobile.diagnostics import describe_run

    image = request.config.getoption('--docker-image')
    if image is None:
        pytest.skip('requires --docker-image')
    root, repository, _, reviewed = candidate
    cfg = review_config(monkeypatch)
    cfg = cfg.model_copy(update={'limits': cfg.limits.model_copy(update={
        'max_attempted_tool_calls': 8 if finish_reason == 'tool_budget' else 100,
        'max_model_turns': 2 if finish_reason == 'model_turns' else 10,
    })})
    tests = [{'argv': ['python', '-B', '-c', 'from value import VALUE; assert VALUE == 2'],
              'cwd': 'project'}]
    calls = [
        {'name': 'read_file', 'arguments': {'path': 'scratch/review.diff'}},
        {'name': 'read_file', 'arguments': {'path': 'project/value.py'}},
        {'name': 'run_command', 'arguments': tests[0]},
    ]
    if finish_reason == 'tool_budget':
        calls.extend({'name': 'list_files', 'arguments': {'directory': 'project'}} for _ in range(12))
    for index, call in enumerate(calls):
        call['provider_id'] = 'review_test_' + str(index)
    store = Store(root)

    class Reviewer(ScriptedProvider):
        async def generate(self, model_request):
            snapshot = store.blobs.json(model_request.context_ref)
            wire = store.blobs.json(snapshot['payload_ref'])
            if len(self.requests) < (3 if finish_reason == 'repeated_work' else 1):
                assert wire.get('tools')
            else:
                assert not wire.get('tools')
                import json
                text = json.dumps(wire)
                assert 'FINAL REPORT REQUIRED NOW' in text
                assert 'Recorded review progress retained' in text
                assert 'assert VALUE == 2' in text
            return await super().generate(model_request)

    responses = [{'text': '', 'tool_calls': calls, 'finish_status': 'tool_calls'}]
    if finish_reason == 'repeated_work':
        for turn in range(2):
            repeated = [{**call, 'provider_id': call['provider_id'] + '_' + str(turn)}
                        for call in calls]
            responses.append({'text': '', 'tool_calls': repeated, 'finish_status': 'tool_calls'})
    responses.append(
        {'text': json.dumps({'verdict': 'approve', 'summary': 'Inspected diff, code and tests.',
                             'tests': tests}), 'tool_calls': [], 'finish_status': 'stop'}
    )
    scripted = Reviewer(responses)
    try:
        result = asyncio.run(run_review(
            store, cfg, {'review_target': reviewed, 'test_command': 'auto'},
            {**sandbox_config(), 'image': image}, [repository], provider=scripted,
        ))
        report = result['workspace_review']
        assert report['status'] == 'approved', result
        assert report['checks_audit']['ok'] and report['audit']['ok']
        assert report['review_copy_unchanged'] and report['checks_copy_unchanged']
        assert len(scripted.requests) == (4 if finish_reason == 'repeated_work' else 2)
        assert describe_run(store, result['run_id'])['tests'][0]['status'] == 'passed'
        assert any(e.event_type == 'tool.skipped' for e in store.events(result['run_id'])) == (
            finish_reason == 'tool_budget'
        )
    finally:
        store.close()


def test_structured_findings_keep_ids_and_acceptance_through_repair_handoff(candidate, monkeypatch, request):
    from local_agent.mobile.repair_controls import repair_evidence

    image = request.config.getoption('--docker-image')
    if image is None:
        pytest.skip('requires --docker-image')
    root, repository, _, reviewed = candidate
    finding = {'id': 'F1', 'location': 'value.py:1', 'observed': 'A boundary case is missing',
               'expected': 'Handle the boundary', 'impact': 'Incorrect behavior at the boundary',
               'acceptance': ['Add a boundary regression and demonstrate the expected result']}
    store = Store(root)
    try:
        result = asyncio.run(run_review(
            store, review_config(monkeypatch),
            {'review_target': reviewed, 'test_command': 'python -m pytest -q'},
            {**sandbox_config(), 'image': image}, [repository],
            provider=provider(verdict='request_changes', findings=[finding]),
        ))
        report = result['workspace_review']
        assert report['status'] == 'changes_requested'
        assert report['findings'] == [finding]
        assert repair_evidence(report, {'question': 'Original task'}, 'review-id')['findings'] == [finding]
    finally:
        store.close()
