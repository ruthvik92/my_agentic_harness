"""Continued workspace context is chronological recent finished history."""

from types import SimpleNamespace

import pytest

from local_agent.mobile.task_context import capture


def test_continuation_carries_failed_in_run_checks_without_completion_report():
    from local_agent.mobile.task_context import unresolved_checks

    failed = {"argv": ["node", "tests/test_obstacles.js"], "exit_code": 1,
              "failure_excerpt": "Wrong block identity"}
    job = {"repair_progress": {"unresolved_checks": [failed]}}
    assert unresolved_checks(job) == [failed]
    job['project_tests'] = {'commands': [{'status': 'passed'}]}
    assert unresolved_checks(job) == []


@pytest.mark.parametrize('status,blocked', [('running', True), ('needs_reconciliation', True), ('budget_exhausted', False)])
def test_active_run_is_rejected_before_submission(monkeypatch, tmp_path, status, blocked):
    from local_agent.mobile.task_context import ensure_previous_terminal
    from local_agent.storage.database import Store

    store = Store(tmp_path)
    store.db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', ('run_previous', status, 'unused', None, 'now'))
    store.db.commit()
    store.close()
    monkeypatch.setattr('local_agent.mobile.task_context.GitWorktrees.load',
                        lambda *_: {'run_id': 'run_previous'})
    server = SimpleNamespace(root=tmp_path)
    if blocked:
        with pytest.raises(ValueError, match='Previous task'):
            ensure_previous_terminal(server, 'ws_target')
    else:
        ensure_previous_terminal(server, 'ws_target')


@pytest.mark.parametrize("count", [1, 2, 8, 12, 100])
def test_context_keeps_first_and_recent_finished_attempts_with_results(monkeypatch, tmp_path, count):
    record = {
        "workspace_id": "ws_target",
        "repository": "/repo",
        "run_id": "run_11",
        "candidate_commit": "candidate",
    }
    monkeypatch.setattr("local_agent.mobile.task_context.GitWorktrees.load", lambda *_: record)
    jobs = [
        {
            "job_id": str(n),
            "thread_id": "chat",
            "workspace_id": "ws_target",
            "mode": "coding",
            "created": n,
            "run_id": f"run_{n}",
            "status": "failed" if n % 2 else "completed",
            "question": "Original task" if n == 0 else f"Follow-up {n}",
            "answer": f"Result {n}",
            "error": f"Failure {n}" if n % 2 else None,
            "project_tests": {"commands": [{"status": "failed", "output": f"assertion {n}"}]},
        }
        for n in range(12)
    ]
    # In-flight entries must not displace finished results or the original goal.
    jobs.extend(
        {**jobs[-1], "created": 100 + n, "run_id": status, "status": status}
        for n, status in enumerate(["queued", "running"])
    )
    jobs.extend(
        [
            {**jobs[0], "created": 200, "thread_id": "other"},
            {**jobs[0], "created": 201, "workspace_id": "ws_other"},
        ]
    )
    server = SimpleNamespace(
        root=tmp_path, jobs=SimpleNamespace(recent=lambda **_: list(reversed(jobs)))
    )
    context = capture(server, "chat", "ws_target", count)
    expected = list(range(12)) if count >= 12 else [0] + (
        list(range(12 - count + 1, 12)) if count > 1 else []
    )
    assert [attempt["run_id"] for attempt in context["attempts"]] == [
        f"run_{n}" for n in expected
    ]
    assert context["n_last_chats"] == count
    if count > 1:
        assert context["attempts"][-1]["answer"] == "Result 11"
        assert context["attempts"][-1]["error"] == "Failure 11"
        assert "assertion 11" in context["attempts"][-1]["tests"]
    assert context["unresolved_checks"][0]["output"] == "assertion 11"
    assert context["original_task"] == "Original task"
    # Capture is refreshed; the previously supplied context remains stable.
    jobs.append(
        {**jobs[0], "created": 300, "run_id": "run_new", "answer": "Latest finished result"}
    )
    refreshed = capture(server, "chat", "ws_target", count)
    assert refreshed["attempts"][-1]["answer"] == (
        "Latest finished result" if count > 1 else "Result 0"
    )
    assert len(refreshed["attempts"]) == min(count, 13)
    assert context["attempts"][-1]["answer"] == f"Result {expected[-1]}"


@pytest.mark.parametrize("value", [True, False, 0, -1, 101, 1.5, "8", None])
def test_invalid_history_limit_is_rejected(value, tmp_path):
    with pytest.raises(ValueError, match="n_last_chats"):
        capture(SimpleNamespace(root=tmp_path), "chat", "workspace", value)


def test_empty_finished_history_does_not_attach_an_active_attempt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "local_agent.mobile.task_context.GitWorktrees.load",
        lambda *_: {"workspace_id": "ws_target", "repository": "/repo"},
    )
    server = SimpleNamespace(
        root=tmp_path,
        jobs=SimpleNamespace(
            recent=lambda **_: [
                {
                    "thread_id": "chat",
                    "workspace_id": "ws_target",
                    "status": "running",
                    "created": 1,
                }
            ]
        ),
    )
    context = capture(server, "chat", "ws_target")
    assert context["attempts"] == []
    assert context["unresolved_checks"] == []
