"""Task outcomes and bounded-label OpenTelemetry metrics derived from durable records."""

from collections import Counter
from datetime import datetime

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from local_agent.storage.blobs import digest


def rate(count, duration_ns):
    return count / (duration_ns / 1e9) if count is not None and duration_ns else None


def report(store, run_id):
    run = store.run(run_id)
    events = store.events(run_id)
    counts = Counter(e.event_type for e in events)
    manifest = store.blobs.json(run["manifest_ref"])
    config = store.blobs.json(manifest["config_ref"])
    models = []
    for row in store.db.execute("SELECT * FROM model_requests WHERE run_id=?", (run_id,)):
        request = store.blobs.json(row["request_ref"])
        if request["provider"] == "harness":
            continue
        response = store.blobs.json(row["response_ref"]) if row["response_ref"] else {}
        usage = response.get("usage") or {}
        duration = response.get("client_duration_seconds")
        total = usage.get("total_duration")
        models.append(
            {
                "request_id": row["id"],
                "attempt": request["attempt"],
                "client_seconds": duration,
                "usage": usage,
                "prompt_tokens_per_second": rate(
                    usage.get("prompt_eval_count"), usage.get("prompt_eval_duration")
                ),
                "decode_tokens_per_second": rate(
                    usage.get("eval_count"), usage.get("eval_duration")
                ),
                "client_minus_provider_seconds": duration - total / 1e9
                if duration is not None and total is not None
                else None,
            }
        )
    tool_rows = store.db.execute(
        "SELECT e.result_ref FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (run_id,),
    ).fetchall()
    results = [store.blobs.json(row[0]) for row in tool_rows if row[0]]
    wall = (
        datetime.fromisoformat(events[-1].timestamp_utc)
        - datetime.fromisoformat(run["created_utc"])
    ).total_seconds()
    attempted = counts["tool.validated"] + counts["tool.rejected"]
    snapshots = [
        store.blobs.json(e.data["snapshot_ref"]) for e in events if e.event_type == "context.built"
    ]
    model_attempts = 0
    model_rejections = 0
    for row in store.db.execute(
        "SELECT t.validated_ref,t.rejected,m.request_ref FROM tool_calls t "
        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (run_id,),
    ):
        if store.blobs.json(row["request_ref"])["provider"] != "harness":
            model_attempts += int(bool(row["validated_ref"] or row["rejected"]))
            model_rejections += int(bool(row["rejected"]))
    data = {
        "run_id": run_id,
        "status": run["status"],
        "verified": run["status"] == "verified",
        "model": config.get("agent", {}).get("model", manifest["model_identity"]),
        "model_identity": manifest["model_identity"],
        "image": manifest["sandbox_image_digest"],
        "window_tokens": config.get("agent", {}).get("window_tokens"),
        "total_wall_seconds": wall,
        "model_turns": len(models),
        "attempted_calls": attempted,
        "invalid_calls": counts["tool.rejected"],
        "model_attempted_calls": model_attempts,
        "invalid_call_rate": model_rejections / model_attempts if model_attempts else 0,
        "policy_denials": sum(
            store.blobs.json(e.data["decision_ref"])["verdict"] == "deny"
            for e in events
            if e.event_type == "policy.evaluated"
        ),
        "recovery_attempts": counts["run.resumed"],
        "retry_decisions": counts["retry.decided"],
        "compactions": counts["context.compacted"],
        "max_estimated_input_tokens": max((s["token_estimate"] for s in snapshots), default=0),
        "tool_seconds": sum(
            r["duration_seconds"] for r in results if r["duration_seconds"] is not None
        ),
        "command_timeouts": sum(r["status"] == "timeout" for r in results),
        "captured_bytes": sum(r.get("captured_bytes", 0) for r in results),
        "models": models,
        "event_counts": dict(counts),
        "capture_mode": "full",
        "residual_interpretation": "unexplained client/provider timing difference",
    }
    # SDK instruments have bounded labels; all identifiers remain in local evidence.
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    meter = provider.get_meter("local_agent", "0.1.0")
    attrs = {"status": run["status"]}
    meter.create_counter("agent.runs").add(1, attrs)
    meter.create_counter("agent.verified_runs").add(int(data["verified"]), attrs)
    for key in (
        "attempted_calls",
        "invalid_calls",
        "policy_denials",
        "compactions",
        "captured_bytes",
        "command_timeouts",
    ):
        meter.create_counter("agent." + key).add(data[key])
    meter.create_histogram("agent.run.duration", unit="s").record(wall, attrs)
    for result in results:
        if result["duration_seconds"] is None:
            continue
        meter.create_histogram("agent.tool.duration", unit="s").record(
            result["duration_seconds"], {"status": result["status"]}
        )
    for snapshot in snapshots:
        meter.create_histogram("agent.context.tokens").record(snapshot["token_estimate"])
    for model in models:
        if model["client_seconds"] is not None:
            meter.create_histogram("agent.model.duration", unit="s").record(model["client_seconds"])
    metrics = reader.get_metrics_data()
    data["otel_metrics"] = metrics.to_json() if metrics else None
    provider.shutdown()
    return data


def checksummed(data):
    from local_agent.storage.blobs import canonical

    return {"report": data, "content_hash": digest(canonical(data))}
