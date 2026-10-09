"""Separate durable trace runs for browser activity, preserving completed model runs."""

from local_agent.contracts import RunManifest, new_id
from local_agent.observability.audit import audit
from local_agent.observability.spans import Spans
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def record(root, thread_id, kind, data):
    store, spans = Store(root), Spans()
    try:
        with spans.boundary("phone.activity"):
            ref = store.blobs.put_json({"kind": "browser_activity", "task": kind})
            run_id = new_id("run")
            store.create_run(
                RunManifest(
                    run_id=run_id,
                    thread_id="thread_" + thread_id,
                    workspace_id=new_id("ws"),
                    config_ref=ref,
                    config_hash=digest(store.blobs.read(ref)),
                    model_identity="phone-controller",
                    package_versions={},
                    mode="live",
                )
            )
            store.transition(run_id, "running")
            store.append(run_id, kind, "phone", {"thread_id": thread_id, **data})
            store.append(run_id, "completion.proposed", "phone", {"answer": "Activity recorded"})
            store.transition(run_id, "completed_unverified")
            checked = audit(store, run_id)
            if not checked["ok"]:
                raise ValueError("Browser activity trace failed audit")
            store.export_jsonl(run_id)
            return run_id
    finally:
        store.close()
        spans.shutdown()
