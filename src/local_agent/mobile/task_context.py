"""Controller-owned working memory for continued workspace tasks."""

from local_agent.mobile.repair_controls import clipped, repair_evidence
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces


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
            "failed_actions": [{key: a.get(key) for key in ("tool", "path", "status", "cause")}
                               for a in data["failures"]],
            "recent_actions": [{key: a.get(key) for key in ("tool", "path", "status")}
                               for a in data["actions"]],
        }
    except (ValueError, OSError):
        return {}
    finally:
        store.close()


def capture(server, thread_id, workspace_id):
    manager = GitWorktrees(Workspaces(server.root))
    record = manager.load(workspace_id)
    if not record:
        return None
    jobs = server.jobs.recent(limit=1000) if hasattr(server.jobs, "recent") else []
    owned = [
        j
        for j in jobs
        if j.get("thread_id") == thread_id
        and (
            (j.get("git_workspace") or {}).get("workspace_id") == workspace_id
            or j.get("workspace_id") == workspace_id
            or (j.get("review_target") or {}).get("workspace_id") == workspace_id
        )
    ]
    latest = next((j for j in owned if j.get("workspace_review")), None)
    latest_report = (latest or {}).get("workspace_review") or {}
    latest_review = (
        repair_evidence(latest_report, {"question": "See original_task in this context"}, latest["job_id"])
        if latest_report.get("status") in {"changes_requested", "failed"} else None
    )
    return {
        "workspace_id": workspace_id,
        "latest_review": latest_review,
        "original_task": clipped(
            next(
                (
                    j.get("repair_original_task") or j.get("question", "")
                    for j in reversed(owned)
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
            for j in owned[:8]
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
