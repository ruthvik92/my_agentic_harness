"""Explicit ownership grants for read-only evidence; never infer grants from prompt text."""

import time

from local_agent.contracts import ExecutionResult
from local_agent.storage.blobs import canonical


def allowed(store, run_id, ref):
    rows = store.db.execute(
        "SELECT e.result_ref FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=? AND e.state='finished'",
        (run_id,),
    ).fetchall()
    for row in rows:
        result = store.blobs.json(row[0])
        if ref in {result.get(k) for k in ("output_ref", "stdout_ref", "stderr_ref")}:
            return True
    return any(
        store.blobs.json(row[0])["blob_ref"] == ref
        for row in store.db.execute("SELECT record_ref FROM artifacts WHERE run_id=?", (run_id,))
    )


def execute(store, run_id, request):
    started = time.monotonic()
    row = store.db.execute(
        "SELECT state,request_ref FROM execution_attempts WHERE id=?", (request.execution_id,)
    ).fetchone()
    if row is None or row[0] != "started" or store.blobs.read(row[1]) != canonical(request):
        raise ValueError("evidence resolver requires exact durable started request")
    ref = request.arguments["evidence_ref"]
    if not allowed(store, run_id, ref):
        raise ValueError("evidence reference is not produced by this run")
    data = store.blobs.read(ref)
    offset, limit = (
        request.arguments.get("byte_offset", 0),
        request.arguments.get("byte_limit", 8192),
    )
    end = min(len(data), offset + limit)
    output = canonical(
        {
            "source_ref": ref,
            "byte_offset": offset,
            "total_bytes": len(data),
            "content": data[offset:end].decode(errors="replace"),
            "next_byte_offset": end if end < len(data) else None,
            "truncated": end < len(data),
        }
    )
    # JSON escaping can expand a slice; keep its preview independently bounded.
    preview = output.decode()[:16384]
    return ExecutionResult(
        execution_id=request.execution_id,
        status="succeeded",
        exit_code=0,
        output_ref=store.blobs.put(output),
        preview=preview,
        duration_seconds=time.monotonic() - started,
        side_effect_status="none",
        captured_bytes=len(output),
        truncated=len(output.decode()) > 16384,
    )
