import asyncio
from datetime import UTC, datetime
from pathlib import Path

from local_agent.doctor import sandbox_config
from local_agent.evaluation.hardware import monitor, sample
from local_agent.evaluation.report import report
from local_agent.models.capabilities import ensure_capabilities
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.storage.blobs import canonical, fsync_directory, private_directory

TASKS = {"calculator": "broken_repo", "mean": "mean_repo", "clamp": "clamp_repo"}


async def evaluate(store, config, windows=(8192, 16384), rounds=1, on_result=None):
    sandbox = sandbox_config()
    root = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
    results = []
    for iteration in range(rounds):
        # Alternate ordering to expose, rather than conceal, warm/order effects.
        order = windows if iteration % 2 == 0 else tuple(reversed(windows))
        for window in order:
            profile = config.model_copy(update={"window_tokens": window})
            capability = await ensure_capabilities(store, profile, sandbox)
            for name, folder in TASKS.items():
                before = await sample()
                samples = [before]
                stop = asyncio.Event()
                monitoring = asyncio.create_task(monitor(samples, stop))
                try:
                    result = await Agent(store, profile, sandbox, capability_report=capability).run(
                        root / folder,
                        (
                            root / ("task.md" if name == "calculator" else folder + "/task.md")
                        ).read_text(),
                        verify_fixture=name,
                    )
                finally:
                    stop.set()
                    await monitoring
                samples.append(await sample())
                item = report(store, result["run_id"])
                item["task"] = name
                item["round"] = iteration + 1
                item["audit"] = audit(store, result["run_id"])
                item["hardware_ref"] = store.blobs.put_json(samples)
                resident = (before.get("ollama_ps") or {}).get("models", [])
                item["model_state_before"] = (
                    "resident"
                    if any(
                        m.get("name") == config.model or m.get("model") == config.model
                        for m in resident
                    )
                    else "not_resident"
                )
                item["capability_probe_before_measurement"] = True
                item["thermal_max_c"] = max(
                    (
                        float(g["temperature_c"])
                        for s in samples
                        for g in s.get("gpus") or []
                        if g["temperature_c"].replace(".", "", 1).isdigit()
                    ),
                    default=None,
                )
                item["peak_vram_mib"] = max(
                    (
                        float(g["memory_used_mib"])
                        for s in samples
                        for g in s.get("gpus") or []
                        if g["memory_used_mib"].replace(".", "", 1).isdigit()
                    ),
                    default=None,
                )
                item["report_ref"] = store.blobs.put_json(item)
                results.append(item)
                store.export_jsonl(result["run_id"])
                if on_result:
                    on_result(item)
    comparison = []
    for window in windows:
        group = [r for r in results if r["window_tokens"] == window]
        comparison.append(
            {
                "window_tokens": window,
                "runs": len(group),
                "verified": sum(r["verified"] and r["audit"]["ok"] for r in group),
                "mean_wall_seconds": sum(r["total_wall_seconds"] for r in group) / len(group),
                "invalid_calls": sum(r["invalid_calls"] for r in group),
                "recovery_attempts": sum(r["recovery_attempts"] for r in group),
            }
        )
    summary = {
        "schema_version": 1,
        "created_utc": datetime.now(UTC).isoformat(),
        "model": config.model,
        "dimension_changed": "context window only",
        "rounds": rounds,
        "comparison": comparison,
        "runs": results,
        "limitations": "Small sequential held-out suite; capability probes warm the model. No cold-start or optimal-model claim.",
    }
    directory = store.control / "reports"
    private_directory(directory)
    ref = store.blobs.put_json(summary)
    target = directory / (ref[7:] + ".json")
    with target.open("xb") as stream:
        stream.write(canonical(summary))
        stream.flush()
        import os

        os.fsync(stream.fileno())
    fsync_directory(directory)
    return {**summary, "report_ref": ref, "report_path": str(target)}
