"""A traced read-only tool/continuation probe, cached by exact deployment inputs."""

import json
import os

from local_agent.contracts import Limits, new_id
from local_agent.models.factory import create_provider
from local_agent.storage.blobs import canonical, digest, fsync_directory, private_directory
from local_agent.tools.registry import definitions


async def ensure_capabilities(store, config, sandbox):
    from local_agent.runtime.agent import Agent

    provider = create_provider(store.blobs, config)
    try:
        metadata = await provider.metadata(config.model)
    finally:
        await provider.close()
    key = digest(
        canonical(
            {
                "digest": metadata["installed"].get("digest"),
                "version": metadata.get("ollama", metadata.get("openai")),
                "provider": config.provider,
                "completion_token_field": config.completion_token_field,
                "sandbox": sandbox["image"],
                "schemas": definitions(),
                "instructions": config.instructions_hash,
                "window": config.window_tokens,
                "reserve": config.output_reserve_tokens,
            }
        )
    )[7:]
    directory = store.control / "capabilities"
    private_directory(directory)
    cache = directory / (key + ".json")
    if cache.exists():
        cached = json.loads(cache.read_text())
        report = store.blobs.json(cached["report_ref"])
        if report["passed"]:
            return report
    source = store.control / "probe_sources" / new_id("probe")
    private_directory(source)
    (source / "probe.txt").write_text("SANDBOX_CAPABILITY_OK\n")
    probe_config = config.model_copy(
        update={
            "tools": ("read_file",),
            "limits": Limits(
                max_model_turns=3,
                max_attempted_tool_calls=6,
                run_timeout_seconds=300,
                model_timeout_seconds=180,
            ),
        }
    )
    task = "Call read_file once with path project/probe.txt. Read its result, then stop calling tools and reply SANDBOX_CAPABILITY_OK. This is a tool capability probe."
    result = await Agent(store, probe_config, sandbox).run(source, task, probe=True)
    passed = result["status"] == "completed_unverified"
    rows = store.db.execute(
        "SELECT t.record_ref,t.validated_ref,t.rejected,m.request_ref FROM tool_calls t "
        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (result["run_id"],),
    ).fetchall()
    rows = [
        row for row in rows if store.blobs.json(row["request_ref"])["provider"] == config.provider
    ]
    passed = (
        passed and len(rows) == 1 and bool(rows[0]["validated_ref"]) and not rows[0]["rejected"]
    )
    if passed:
        call = store.blobs.json(rows[0]["record_ref"])
        passed = (
            call["name"] == "read_file"
            and store.blobs.json(call["arguments_ref"]).get("path") == "project/probe.txt"
        )
    passed = passed and "SANDBOX_CAPABILITY_OK" in result.get("answer", "")
    report = {
        "passed": passed,
        "run_id": result["run_id"],
        "model": config.model,
        "key": key,
        "checks": [
            "valid_tool_selection",
            "schema_adherence",
            "tool_result_continuation",
            "sensible_stop",
        ],
    }
    ref = store.blobs.put_json(report)
    if not passed:
        raise RuntimeError(f"model capability probe failed; inspect {result['run_id']}")
    fd = os.open(cache, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical({"report_ref": ref}))
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(directory)
    return report
