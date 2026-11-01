"""Authenticated browser controls; models have no merge authority."""

import json
import os

from local_agent.mobile.activity import record
from local_agent.mobile.jobs import publish
from local_agent.mobile.workspace_review import test_argv
from local_agent.observability.audit import audit
from local_agent.storage.database import Store
from local_agent.storage.locks import run_lock
from local_agent.workspace.git import git
from local_agent.workspace.options import validate_options
from local_agent.workspace.review import capture_target, merge_candidate, require_clean, target


def submit_workspace_review(server, thread_id, payload, *, config_override=None, extra_metadata=None):
    allowed = {"answer_job_id", "candidate_commit", "model_id", "test_command", "working_directory"}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError(
            "Workspace review requires answer, candidate, reviewer, test command and directory"
        )
    test_argv(payload["test_command"])
    directory = validate_options({"working_directory": payload["working_directory"]})[
        "working_directory"
    ]
    with server.threads._lock, run_lock(server.root / "control"):
        if hasattr(server, "loops"):
            active = server.loops.active(thread_id=thread_id)
            if active and (extra_metadata or {}).get("loop_id") != active["loop_id"]:
                raise ValueError("Stop the active loop before starting another review")
        thread = server.threads.get(thread_id)
        pending = server.jobs.get(thread.get("pending_job"))
        if pending and pending["status"] in {"queued", "running"}:
            raise ValueError("This thread already has a pending question")
        if len(thread["messages"]) >= 200:
            raise ValueError("Thread is full; start a new chat")
        answer = next(
            (
                m
                for m in thread["messages"]
                if m.get("role") == "assistant" and m.get("job_id") == payload["answer_job_id"]
            ),
            None,
        )
        job = server.jobs.get(payload["answer_job_id"])
        if (
            not answer
            or not job
            or job.get("thread_id") != thread_id
            or job.get("mode") != "coding"
            or job["status"] != "completed"
        ):
            raise ValueError("Choose a completed coding answer in this chat")
        frozen = job.get("git_workspace") or {}
        if frozen.get("candidate_commit") != payload["candidate_commit"]:
            raise ValueError("Requested commit differs from the selected coding answer")
        reviewed = capture_target(
            server.root,
            frozen.get("workspace_id"),
            payload["candidate_commit"],
            server.allowed_roots,
            directory,
        )
        if reviewed["source_run_id"] != job.get("run_id"):
            raise ValueError("This workspace has a newer task; review its latest coding answer")
        cfg = config_override or server.models.select_reviewer(payload["model_id"], workspace=True)
        if not os.environ.get(cfg.api_key_env):
            raise ValueError("Set " + cfg.api_key_env + " in the server's launch terminal")
        original_task = str(job.get("question", ""))
        for message in thread["messages"]:
            if message.get("role") != "assistant":
                continue
            previous = server.jobs.get(message.get("job_id"))
            if (
                previous
                and previous.get("thread_id") == thread_id
                and previous.get("mode") == "coding"
                and (previous.get("git_workspace") or {}).get("workspace_id")
                == frozen.get("workspace_id")
            ):
                original_task = str(previous.get("question", original_task))
                break
        request = {
            "mode": "workspace-review",
            "review_target": reviewed,
            "test_command": payload["test_command"],
            "context": "Original coding task: "
            + original_task[:8000]
            + "\nSelected follow-up question: "
            + str(job.get("question", ""))[:2000]
            + "\nPrior answer: "
            + answer["content"][:4000],
        }
        prior = server.jobs.get(job.get("repair_review_job_id")) or {}
        previous = (prior.get("workspace_review") or {}).get("findings")
        if not previous and job.get("loop_id") and hasattr(server, "loops"):
            last = server.loops.load(job["loop_id"]).get("last_review") or {}
            previous = last.get("findings")
        if previous:
            concise = [{"id": item.get("id"), "location": str(item.get("location", ""))[:100],
                        "observed": str(item.get("observed", ""))[:160],
                        "expected": str(item.get("expected", ""))[:160],
                        "acceptance": [str(v)[:120] for v in item.get("acceptance", [])[:1]]}
                       for item in previous[:8]]
            request["context"] = ("Untrusted prior findings; retain IDs when still unresolved:\n"
                                  + json.dumps(concise, ensure_ascii=False) + "\n" + request["context"])
        job_id = server.jobs.submit(
            request,
            config=cfg,
            metadata={
                "thread_id": thread_id,
                "question": "Review workspace commit " + reviewed["candidate_commit"],
                "kind": "workspace_review",
                "has_image": False,
                "review_target": reviewed,
                "source_run_ids": [reviewed["source_run_id"]],
                "usage_baseline_model": server.usage_baseline(),
                **(extra_metadata or {}),
            },
        )
        server.threads.update(thread_id, pending_job=job_id)
        return job_id


def get_review(server, job_id, thread_id=None):
    job = server.jobs.get(job_id)
    if not job or (thread_id and job.get("thread_id") != thread_id):
        raise ValueError("Review job not found in this chat")
    report = job.get("workspace_review")
    if job.get("kind") != "workspace_review" or not report:
        raise ValueError("No workspace report is available for this job")
    return job, report


def merge_review(server, thread_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"review_job_id", "candidate_commit"}:
        raise ValueError("Merge requires the reviewed job and exact candidate commit")
    with server.threads._lock, run_lock(server.root / "control"):
        thread = server.threads.get(thread_id)
        pending = server.jobs.get(thread.get("pending_job"))
        if pending and pending["status"] in {"queued", "running"}:
            raise ValueError("Wait for this chat's active job before merging")
        job, report = get_review(server, payload["review_job_id"], thread_id)
        if (
            job["status"] != "completed"
            or report["status"] != "approved"
            or not report.get("checks_passed")
            or not report.get("audit", {}).get("ok")
            or not report.get("checks_audit", {}).get("ok")
            or not report.get("inspected_files_and_diff")
            or not report.get("review_copy_unchanged")
            or not report.get("checks_copy_unchanged")
            or report.get("verdict", {}).get("verdict") != "approve"
        ):
            raise ValueError(
                "Only an approved report with passing checks and inspection evidence can merge"
            )
        reviewed = report["target"]
        if payload["candidate_commit"] != reviewed["candidate_commit"]:
            raise ValueError("Merge commit differs from the reviewed commit")
        if (report.get("merge") or {}).get("status") == "merged":
            return report["merge"]
        store = Store(server.root, readonly=True)
        try:
            for run_id in {report["reviewer_run_id"], report["checks_run_id"],
                           *report.get("checks_run_ids", [])}:
                if not audit(store, run_id)["ok"]:
                    raise ValueError(
                        "Review evidence no longer passes audit; inspect before merging"
                    )
        finally:
            store.close()
        current = target(
            server.root,
            reviewed["workspace_id"],
            reviewed["candidate_commit"],
            server.allowed_roots,
        )
        if (
            current["run_id"] != reviewed["source_run_id"]
            or current["repository"] != reviewed["repository"]
        ):
            raise ValueError("Review workspace changed; inspect its current candidate")
        # Reconcile a crash between successful Git merge and durable completion recording.
        if (report.get("merge") or {}).get("status") == "merging":
            from pathlib import Path

            repository = Path(reviewed["repository"])
            head = git("-C", repository, "rev-parse", "HEAD").decode().strip()
            branch = git("-C", repository, "symbolic-ref", "--short", "HEAD").decode().strip()
            if head == reviewed["candidate_commit"] and branch == reviewed["source_branch"]:
                require_clean(repository, head)
                report["merge"] = {
                    "status": "merged",
                    "commit": head,
                    "branch": branch,
                    "repository": str(repository),
                    "reconciled": True,
                }
        if not report.get("merge") or report["merge"].get("status") != "merged":
            activity = record(
                server.root,
                thread_id,
                "workspace.merge_requested",
                {
                    "review_job_id": job["job_id"],
                    "target": reviewed,
                },
            )
            report["merge"] = {"status": "merging", "activity_run_id": activity}
            publish(server.jobs.directory / job["job_id"] / "workspace-review.json", report)
            publish(server.jobs.directory / job["job_id"] / "status.json", job)
            try:
                report["merge"] = merge_candidate(server.root, reviewed, server.allowed_roots)
            except (RuntimeError, ValueError, OSError) as exc:
                report["merge"] = {"status": "rejected", "reason": str(exc)}
                publish(server.jobs.directory / job["job_id"] / "workspace-review.json", report)
                publish(server.jobs.directory / job["job_id"] / "status.json", job)
                raise
        activity = record(
            server.root,
            thread_id,
            "workspace.merged",
            {
                "review_job_id": job["job_id"],
                "merge": report["merge"],
            },
        )
        for message in thread["messages"]:
            if message.get("job_id") == job["job_id"]:
                message["workspace_review"] = report
        thread.setdefault("activity_runs", []).append(activity)
        server.threads.update(
            thread_id, messages=thread["messages"], activity_runs=thread["activity_runs"]
        )
        publish(server.jobs.directory / job["job_id"] / "workspace-review.json", report)
        publish(server.jobs.directory / job["job_id"] / "status.json", job)
        return report["merge"]
