"""Controller-owned working memory for continued workspace tasks."""

from local_agent.mobile.repair_controls import clipped, repair_evidence
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces

DEFAULT_N_LAST_CHATS = 8


def ensure_previous_terminal(server, workspace_id):
    """Reject a known active continuation before creating a loop or browser job."""
    if not workspace_id or not (server.root / "control/agent.db").exists():
        return
    record = GitWorktrees(Workspaces(server.root)).load(workspace_id)
    if not record or not record.get("run_id"):
        return
    from local_agent.observability.events import TERMINAL
    from local_agent.storage.database import Store

    store = Store(server.root, readonly=True)
    try:
        row = store.db.execute("SELECT status FROM runs WHERE id=?", (record["run_id"],)).fetchone()
        if row is not None and row["status"] not in TERMINAL:
            raise ValueError("Previous task is active; stop or finish it before continuing")
        if row is not None and row["status"] == "needs_reconciliation":
            raise ValueError("Previous task has unresolved executions; reconcile it before continuing")
    finally:
        store.close()


def unresolved_checks(job):
    commands = (job.get("project_tests") or {}).get("commands", [])
    if commands:
        return [c for c in commands if c.get("status") != "passed"][:16]
    return (job.get("repair_progress") or {}).get("unresolved_checks", [])[:16]


def validate_n_last_chats(value):
    if type(value) is not int or not 1 <= value <= 100:
        raise ValueError("n_last_chats must be an integer from 1 to 100")
    return value


def failure_evidence(server, job):
    """Bounded, controller-derived facts, including errors hidden by old summaries."""
    if not job.get("run_id") or not (server.root / "control/agent.db").exists():
        return {}
    from local_agent.mobile.diagnostics import describe_run
    from local_agent.storage.database import Store

    store = Store(server.root, readonly=True)
    try:
        data = describe_run(store, job["run_id"], action_limit=4)
        return {
            "summary": data["summary"], "counts": data["counts"],
            "provider_errors": data["provider_errors"][-2:],
            "failed_actions": [{key: a.get(key) for key in ("tool", "path", "status", "cause", "command", "failure", "feedback")}
                               for a in data["failures"]],
            "recent_actions": [{key: a.get(key) for key in ("tool", "path", "status")}
                               for a in data["actions"]],
        }
    except (ValueError, OSError):
        return {}
    finally:
        store.close()


def capture(server, thread_id, workspace_id, n_last_chats=DEFAULT_N_LAST_CHATS):
    n_last_chats = validate_n_last_chats(n_last_chats)
    manager = GitWorktrees(Workspaces(server.root))
    record = manager.load(workspace_id)
    if not record:
        return None
    jobs = server.jobs.recent(limit=1000) if hasattr(server.jobs, "recent") else []
    owned = [
        j
        for j in jobs
        if j.get("thread_id") == thread_id
        and j.get("status") in {"completed", "failed", "interrupted", "cancelled"}
        and (
            (j.get("git_workspace") or {}).get("workspace_id") == workspace_id
            or j.get("workspace_id") == workspace_id
            or (j.get("review_target") or {}).get("workspace_id") == workspace_id
        )
    ]
    history = sorted(owned, key=lambda j: j.get("created", 0))
    # Keep the first attempt and the newest N-1 without duplicating overlaps.
    retained = history if len(history) <= n_last_chats else (
        history[:1] + (history[-(n_last_chats - 1):] if n_last_chats > 1 else [])
    )
    latest = next((j for j in reversed(history) if j.get("workspace_review")), None)
    latest_report = (latest or {}).get("workspace_review") or {}
    latest_review = (
        repair_evidence(latest_report, {"question": "See original_task in this context"}, latest["job_id"])
        if latest_report.get("status") in {"changes_requested", "failed"} else None
    )
    return {
        "workspace_id": workspace_id,
        "n_last_chats": n_last_chats,
        "git_history": {"host": "Host-managed Git worktree and published candidate",
                        "sandbox": "Project copy; host Git metadata is not mounted",
                        "base_commit": record.get("base_commit"),
                        "candidate_commit": record.get("candidate_commit")},
        "latest_review": latest_review,
        "unresolved_checks": unresolved_checks(history[-1]) if history else [],
        "recovery_plan": "Read unresolved checks and retained failure evidence. Correct paths or prepare missing dependencies in Docker, make a targeted repair, then rerun the checks.",
        "original_task": clipped(
            next(
                (
                    j.get("repair_original_task") or j.get("question", "")
                    for j in history
                    if j.get("mode") == "coding"
                ),
                "",
            ),
            8000,
        ),
        "expected": {
            key: record.get(key)
            for key in ("workspace_id", "run_id", "candidate_commit", "repository")
        },
        "attempts": [
            {
                "run_id": j.get("run_id"),
                "status": j["status"],
                "error": clipped(j.get("error") or "", 1000),
                "answer": clipped(j.get("answer") or "", 3000),
                "diagnostics": clipped(failure_evidence(server, j), 5000),
                "tests": clipped(j.get("project_tests") or {}, 12000),
                "review": clipped(j.get("workspace_review") or {}, 16000),
            }
            for j in retained
        ],
    }


def attach(request, context):
    if (
        not isinstance(context, dict)
        or not isinstance(context.get("expected"), dict)
        or request.get("mode") != "coding"
        or context.get("workspace_id") != request.get("continue_workspace_id")
        or context["expected"].get("repository") != request.get("workspace")
    ):
        raise ValueError("Task context does not match the continued workspace")
    return {**request, "task_context": context}
