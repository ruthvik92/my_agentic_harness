"""Retire a killed browser controller without inference or mutation replay."""

import asyncio

from local_agent.observability.events import TERMINAL
from local_agent.observability.spans import Spans
from local_agent.storage.database import Store
from local_agent.storage.locks import run_lock


def retire_timed_out_run(root, run_id):
    # subprocess.run has killed and waited for its child. The lease also proves
    # that a replacement controller has not started using this data root.
    with run_lock(root / "control"):
        store = Store(root)
        spans = Spans()
        try:
            run = store.run(run_id)
            if run["status"] in TERMINAL:
                return {"status": run["status"], "retired": False}
            pending = store.db.execute(
                "SELECT e.id FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
                "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=? "
                "AND e.state NOT IN ('finished','reconciled')", (run_id,),
            ).fetchall()
            if pending:
                from local_agent.doctor import sandbox_config
                from local_agent.executor.docker import DockerExecutor
                from local_agent.workspace.manager import Workspaces

                executor = DockerExecutor(store, Workspaces(root), sandbox_config()["image"])
                asyncio.run(executor.emergency_cleanup(run_id))
            status = ("needs_reconciliation" if pending else
                      "cancelled" if run["status"] == "created" else "budget_exhausted")
            with spans.boundary("browser.timeout_cleanup"):
                events = store.events(run_id)
                last = events[-1]
                failed_requests = {e.data.get("request_id") for e in events
                                   if e.event_type == "model.failed"}
                for row in store.db.execute(
                    "SELECT id FROM model_requests WHERE run_id=? AND response_ref IS NULL", (run_id,),
                ).fetchall():
                    if row["id"] not in failed_requests:
                        last = store.append(run_id, "model.failed", "runtime", {
                            "request_id": row["id"], "type": "BrowserControllerTimeout",
                            "detail": "Controller killed before a response was persisted; request not replayed.",
                        }, causes=(last.event_id,))
                marked = {cid for event in events
                          for cid in event.data.get("skipped_call_ids", [])}
                skipped = [row[0] for row in store.db.execute(
                    "SELECT t.id FROM tool_calls t JOIN model_requests m ON m.id=t.request_id "
                    "WHERE m.run_id=? AND t.validated_ref IS NULL AND t.rejected=0", (run_id,),
                ) if row[0] not in marked]
                if skipped:
                    last = store.append(run_id, "tool.skipped", "runtime", {
                        "skipped_call_ids": skipped, "terminal_reason": status,
                        "reason": "BrowserControllerTimeout",
                    }, causes=(last.event_id,))
                store.transition(run_id, status, causes=(last.event_id,), reason={
                    "type": "BrowserControllerTimeout",
                    "detail": "Browser controller exceeded its wall deadline and was killed. "
                    "Work preserved; uncertain executions require reconciliation; no actions replayed.",
                })
            return {"status": status, "retired": True,
                    "pending_execution_ids": [row[0] for row in pending]}
        finally:
            store.close()
            spans.shutdown()
