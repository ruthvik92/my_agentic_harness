"""One browser view joins workspace files, attempts, containers and failure evidence."""

import asyncio
import json
from pathlib import Path

from local_agent.contracts import ExecutionSettings
from local_agent.executor.docker import DockerExecutor
from local_agent.executor.maintenance import sweep
from local_agent.mobile.diagnostics import describe_run
from local_agent.storage.database import Store
from local_agent.storage.locks import run_lock
from local_agent.workspace.git import GitWorktrees
from local_agent.workspace.manager import Workspaces


def failures(store, run_id):
    result = []
    if not run_id:
        return result
    try:
        events = store.events(run_id)
    except ValueError:
        return result
    for event in events:
        if event.event_type != "execution.finished":
            continue
        value = store.blobs.json(event.data["result_ref"])
        if value.get("status") == "succeeded":
            continue
        row = store.db.execute(
            "SELECT record_ref FROM tool_calls WHERE id=?", (event.tool_call_id,)
        ).fetchone()
        call = store.blobs.json(row[0]) if row else {}
        args = store.blobs.json(call["arguments_ref"]) if call else {}
        result.append(
            {
                "tool": call.get("name"),
                "path": args.get("path"),
                "exit_code": value.get("exit_code"),
                "cause": str(value.get("preview", ""))[:2000],
                "execution_id": value["execution_id"],
                "output_ref": value.get("output_ref"),
            }
        )
    return result[-3:]


def view(server, thread_id):
    server.threads.get(thread_id)
    jobs = [j for j in server.usage_jobs() if j.get("thread_id") == thread_id]
    if not (server.root / "control/agent.db").exists():
        return {"data_root": str(server.root), "workspaces": []}
    store = Store(server.root, readonly=True)
    manager = GitWorktrees(Workspaces(server.root))
    groups = {}
    try:
        for job in jobs:
            ws = (
                (job.get("git_workspace") or {}).get("workspace_id")
                or job.get("workspace_id")
                or (job.get("review_target") or {}).get("workspace_id")
                or ((job.get("workspace_review") or {}).get("target") or {}).get("workspace_id")
            )
            if not ws and job.get("run_id"):
                try:
                    ws = store.blobs.json(store.run(job["run_id"])["manifest_ref"])["workspace_id"]
                except ValueError:
                    continue
            if not ws:
                continue
            record = manager.load(ws)
            if not record or not any(
                Path(record["repository"]).resolve().is_relative_to(r) for r in server.allowed_roots
            ):
                continue
            group = groups.setdefault(
                ws,
                {
                    "workspace_id": ws,
                    "git_workspace": manager.public(ws),
                    "attempts": [],
                    "data_root": str(server.root),
                    "ledger": str(store.control / "agent.db"),
                    "trace_directory": str(store.control / "runs"),
                    "container": None,
                    "profile_name": job.get("profile_name"),
                    "mode": "coding",
                    "workspace": str(Path(record["worktree"]).parent),
                },
            )
            if job.get("mode") == "coding":
                if not group.get("profile_name"):
                    group["profile_name"] = job.get("profile_name")
                if not group.get("execution_mode"):
                    group["execution_mode"] = job.get("execution_mode")
            diagnostics = None
            if job.get("run_id") and job["status"] in {"failed", "interrupted"}:
                try:
                    diagnostics = describe_run(store, job["run_id"], action_limit=6)
                except ValueError:
                    pass
            group["attempts"].append(
                {
                    **{
                        key: job.get(key)
                        for key in (
                            "job_id",
                            "run_id",
                            "status",
                            "error",
                            "model",
                            "profile_name",
                            "kind",
                            "created",
                        )
                    },
                    "diagnostics": diagnostics,
                    "failure_details": (diagnostics["failures"] if diagnostics else failures(store, job.get("run_id")))
                    if job["status"] in {"failed", "interrupted"}
                    else [],
                    "job_directory": str(server.jobs.directory / job["job_id"]),
                }
            )
        for ws, group in groups.items():
            path = store.control / "containers" / (ws + ".json")
            if not path.exists():
                continue
            record = json.loads(path.read_text())
            try:
                executor = DockerExecutor(
                    store,
                    Workspaces(server.root),
                    record["image"],
                    settings=ExecutionSettings.model_validate(record["settings"]),
                )
                container = executor.make_manager(lambda *_: None)
                info = asyncio.run(container.inspect(record["container_id"]))
                if info is not None:
                    container.verify(info, record)
                group["container"] = {
                    "id": record["container_id"],
                    "name": info["Name"].lstrip("/") if info else record.get("container_name"),
                    "state": info["State"]["Status"] if info else "removed",
                    "activity": record.get("state"),
                    "active_execution_id": record.get("active_execution_id"),
                    "image": record["image"],
                }
            except (OSError, RuntimeError, ValueError, PermissionError):
                group["container"] = {"state": "unavailable", "name": record.get("container_name")}
        return {"data_root": str(server.root), "workspaces": list(groups.values())}
    finally:
        store.close()


def stop(server, thread_id, workspace_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"container_id"}:
        raise ValueError("Stop requires the displayed container ID")
    with server.threads._lock, run_lock(server.root / "control"):
        if hasattr(server, "loops") and server.loops.active(
            thread_id=thread_id, workspace_id=workspace_id
        ):
            raise ValueError("Stop the active loop before stopping its container")
        thread = server.threads.get(thread_id)
        pending = server.jobs.get(thread.get("pending_job"))
        if pending and pending["status"] in {"queued", "running"}:
            raise ValueError(
                "Stop the active loop or wait for the current attempt before stopping its container"
            )
        selected = next(
            (w for w in view(server, thread_id)["workspaces"] if w["workspace_id"] == workspace_id),
            None,
        )
        if (
            not selected
            or not selected["container"]
            or selected["container"].get("id") != payload["container_id"]
        ):
            raise ValueError("Workspace container changed; refresh the workspace details")
        path = server.root / "control/containers" / (workspace_id + ".json")
        record = json.loads(path.read_text())
        result = asyncio.run(
            sweep(
                server.root,
                record["image"],
                ExecutionSettings.model_validate(record["settings"]),
                workspace_id=workspace_id,
            )
        )
        if result.get("maintenance_run_id"):
            current = server.threads.get(thread_id)
            server.threads.update(
                thread_id,
                activity_runs=[*current.get("activity_runs", []), result["maintenance_run_id"]],
            )
        return result
