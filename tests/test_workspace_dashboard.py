import copy

import pytest
from test_review_repair import repair_server  # noqa: F401
from test_workspace_review import candidate  # noqa: F401

from local_agent.mobile.profile_turns import submit_profile_turn
from local_agent.mobile.web import BrowserServer
from local_agent.mobile.workspace_sessions import stop, view
from local_agent.storage.database import Store


def test_workspace_view_joins_attempts_and_failed_chat_is_durable(repair_server):  # noqa: F811
    server, tid, _, jobs, _, report, project = repair_server
    Store(server.root).close()
    failed = {
        **copy.deepcopy(jobs["a" * 32]),
        "job_id": "d" * 32,
        "run_id": None,
        "status": "failed",
        "created": 5,
        "model": "local",
        "provider": "ollama",
        "error": "patch requires one exact match",
        "question": "Fix review findings",
    }
    jobs[failed["job_id"]] = failed
    server.jobs.directory = server.root / "phone/jobs"
    server.usage_jobs = lambda: list(jobs.values())
    BrowserServer.finish(server, failed, trace=False)
    BrowserServer.finish(server, failed, trace=False)
    messages = server.threads.get(tid)["messages"]
    saved = [m for m in messages if m.get("job_id") == failed["job_id"]]
    assert len(saved) == 1
    assert saved[0]["job_status"] == "failed"
    assert "patch requires one exact match" in saved[0]["content"]
    data = view(server, tid)
    assert len(data["workspaces"]) == 1
    workspace = data["workspaces"][0]
    assert workspace["workspace_id"] == report["target"]["workspace_id"]
    assert workspace["git_workspace"]["worktree"] == str(project)
    assert workspace["ledger"] == str(server.root / "control/agent.db")
    assert any(a["error"] == failed["error"] for a in workspace["attempts"])
    assert len(workspace["attempts"]) == 3
    # A saved reply can outlive its ledger evidence without hiding the workspace.
    jobs[failed["job_id"]]["run_id"] = "run_" + "f" * 32
    missing = next(a for a in view(server, tid)["workspaces"][0]["attempts"]
                   if a["job_id"] == failed["job_id"])
    assert missing["diagnostics"] is None
    assert missing["failure_details"] == []
    with pytest.raises(ValueError):
        stop(server, tid, workspace["workspace_id"], {"container_id": "forged"})
    foreign = server.threads.create("Different chat")
    assert not view(server, foreign)["workspaces"]
    server.allowed_roots = [server.root]
    assert not view(server, tid)["workspaces"]


def test_continue_carries_older_workspace_evidence_in_a_file_context(repair_server):  # noqa: F811
    server, tid, _, jobs, captured, report, _ = repair_server
    server.jobs.recent = lambda **_: list(reversed(list(jobs.values())))
    jobs["a" * 32]["error"] = "Old failure beyond recent chat"
    jobs["a" * 32]["status"] = "failed"
    submit_profile_turn(
        server,
        tid,
        {
            "profile_name": "coder.yaml",
            "workspace": report["target"]["repository"],
            "continue_workspace_id": report["target"]["workspace_id"],
            "question": "Try again",
        },
        force_tests=True,
    )
    task, cfg, metadata = captured[0]
    context = task["task_context"]
    assert context["original_task"] == "Implement text statistics"
    assert "Old failure beyond recent chat" in str(context["attempts"])
    assert context["expected"]["run_id"] == report["target"]["source_run_id"]
    assert cfg.project_tests
    assert report["target"]["source_run_id"] in metadata["source_run_ids"]
