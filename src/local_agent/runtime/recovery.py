import json
from datetime import UTC, datetime

from local_agent.contracts import ExecutionRequest, ExecutionResult, ModelResponse, ToolCall
from local_agent.executor.docker import OUTPUT_CAP, docker
from local_agent.runtime.image_capture import capture_image
from local_agent.runtime.image_messages import image_messages
from local_agent.runtime.tool_results import result_preview
from local_agent.storage.blobs import canonical


class NeedsReconciliation(RuntimeError):
    pass


async def reconcile(agent, row):
    store = agent.store
    execution = ExecutionRequest.model_validate_json(store.blobs.read(row["request_ref"]))
    marker = store.control / "attempts" / (execution.execution_id + ".json")
    result = None
    outcome = "unknown"
    if marker.exists():
        data = json.loads(marker.read_text())
        result = ExecutionResult.model_validate_json(store.blobs.read(data["result_ref"]))
        if result.execution_id != execution.execution_id:
            raise NeedsReconciliation("recovered result identity mismatch")
        outcome = "published_result"
    else:
        mapping = agent.executor.mapping(execution.execution_id)
        if mapping:
            expected = {
                "execution_id": execution.execution_id, "workspace_id": execution.workspace_id,
                "run_id": agent.run_id, "tool_call_id": execution.call_id,
            }
            if any(mapping.get(key) != value for key, value in expected.items()):
                raise NeedsReconciliation("execution container mapping identity mismatch")
            manager = agent.executor.make_manager(
                lambda kind, data: agent.event(kind, "recovery", data)
            )
            if mapping.get("owner") != manager.owner:
                raise NeedsReconciliation("execution container owner mismatch")
            if mapping["execution_mode"] == "persistent":
                # The keeper's logs/exit status cannot prove an exec command's outcome.
                await manager.stop(
                    execution.workspace_id, expected_container_id=mapping["container_id"],
                    expected_execution_id=execution.execution_id,
                )
                agent.last = store.reconcile_execution(
                    agent.run_id, execution.execution_id, None, "unknown",
                    causes=(agent.last.event_id,),
                )
                raise NeedsReconciliation(
                    "persistent command result was not published; mutation will not be replayed"
                )
            if mapping["execution_mode"] != "ephemeral":
                raise NeedsReconciliation("invalid execution mode in mapping")
        name = mapping["container_id"] if mapping else "local-agent-" + execution.execution_id
        try:
            info = await agent.executor.inspect(name)
        except RuntimeError:
            info = None
        if info is not None:
            labels = info["Config"].get("Labels") or {}
            required = {
                "local-agent.execution": execution.execution_id,
                "local-agent.workspace": execution.workspace_id,
                "local-agent.run": agent.run_id,
            }
            if any(labels.get(key) != value for key, value in required.items()) or (
                mapping and (
                    info["Id"] != mapping["container_id"]
                    or labels.get("local-agent.owner") != mapping["owner"]
                )
            ):
                raise NeedsReconciliation("recovery container ownership mismatch")
            inspect_ref = store.blobs.put_json(info)
            active = info["State"]["Running"]
            if active:
                agent.event(
                    "retry.decided",
                    "recovery",
                    {
                        "execution_id": execution.execution_id,
                        "selected_action": "terminate_active_container",
                        "inspect_ref": inspect_ref,
                        "reason_source": "deterministic_rule",
                        "rule": "recovery.terminate-v1",
                    },
                )
                await docker("kill", name, check=False)
                info = await agent.executor.inspect(name)
            if info["State"]["Status"] == "exited":
                logs = await docker("logs", name, check=False)
                captured = logs[:OUTPUT_CAP]
                result = ExecutionResult(
                    execution_id=execution.execution_id,
                    status="cancelled"
                    if active
                    else ("succeeded" if info["State"]["ExitCode"] == 0 else "failed"),
                    exit_code=info["State"]["ExitCode"],
                    output_ref=store.blobs.put(captured),
                    preview=captured[:16384].decode(errors="replace"),
                    duration_seconds=None,
                    truncated=len(logs) > 16384,
                    side_effect_status="unknown",
                    captured_bytes=len(captured),
                )
                outcome = "container_logs"
    if result is not None:
        capture_image(agent, execution, result)
    agent.last = store.reconcile_execution(
        agent.run_id, execution.execution_id, result, outcome, causes=(agent.last.event_id,)
    )
    if result is None:
        raise NeedsReconciliation(
            f"container/result missing for {execution.execution_id}; mutation will not be replayed"
        )
    await agent.executor.release(execution.execution_id)
    return result


def preview(result):
    return {
        "status": result.status,
        "exit_code": result.exit_code,
        "preview": result.preview,
        "evidence_ref": result.output_ref,
        "truncated": result.truncated,
    }


async def restore(agent, run_id):
    store = agent.store
    run = store.run(run_id)
    if run["status"] not in {"created", "running"}:
        raise ValueError(f"run cannot resume from {run['status']}")
    agent.run_id = run_id
    agent.created = True
    agent.last = store.events(run_id)[-1]
    manifest = store.blobs.json(run["manifest_ref"])
    config = store.blobs.json(manifest["config_ref"])
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.storage.bundles import roots

    existing, _ = roots(store, run_id)
    agent.store.blobs.budget -= sum(len(store.blobs.read(ref)) for ref in existing)
    agent.store.blobs.budget_refs.update(existing)
    if agent.store.blobs.budget < 0:
        raise OSError("persisted evidence exceeds the run budget")
    from local_agent.policy.engine import OFFLINE_HASH
    from local_agent.storage.blobs import digest

    if digest(store.blobs.read(manifest["config_ref"])) != manifest["config_hash"]:
        raise NeedsReconciliation("resolved configuration hash mismatch")
    if bool(config["model_metadata"].get("scripted")) != isinstance(
        agent.provider, ScriptedProvider
    ):
        raise NeedsReconciliation("provider changed; no automatic inference")
    if agent.sandbox != config["sandbox"]:
        raise NeedsReconciliation("sandbox changed; no automatic dispatch")
    if not isinstance(agent.provider, ScriptedProvider):
        metadata = await agent.provider.metadata(agent.config.model)
        if metadata["installed"]["digest"] != manifest["model_identity"]:
            raise NeedsReconciliation("model digest changed; no automatic inference")

    from local_agent.contracts import AgentConfig

    resolved_agent = AgentConfig.model_validate_json(canonical(config["agent"]))
    if resolved_agent != agent.config:
        raise NeedsReconciliation("agent configuration changed; no automatic dispatch")
    if config["policy_hash"] != OFFLINE_HASH:
        raise NeedsReconciliation("effective policy changed; no automatic dispatch")
    agent.run_id = run_id
    agent.workspace_id = manifest["workspace_id"]
    agent.path = agent.workspaces.path(agent.workspace_id)
    if agent.workspaces.git_info(agent.workspace_id):
        from local_agent.workspace.git import GitWorktrees

        worktrees = GitWorktrees(agent.workspaces)
        worktrees.verify(worktrees.load(agent.workspace_id))
    agent.baseline = store.control / "baselines" / agent.workspace_id
    agent.created = True
    elapsed = (datetime.now(UTC) - datetime.fromisoformat(run["created_utc"])).total_seconds()
    import time

    agent.deadline = time.monotonic() + agent.config.limits.run_timeout_seconds - max(0, elapsed)
    prior = store.events(run_id)
    agent.last = prior[-1]
    if run["latest_checkpoint"]:
        from local_agent.contracts import Checkpoint

        checkpoint_row = store.db.execute(
            "SELECT * FROM checkpoints WHERE id=?", (run["latest_checkpoint"],)
        ).fetchone()
        checkpoint = Checkpoint.model_validate_json(store.blobs.read(checkpoint_row["record_ref"]))
        if checkpoint.run_id != run_id or checkpoint.completed_event_seq > prior[-1].run_seq:
            raise NeedsReconciliation("checkpoint does not match committed history")
    if run["status"] == "created":
        agent.last = store.transition(run_id, "running", causes=(agent.last.event_id,))
    agent.event(
        "run.resumed",
        "recovery",
        {
            "status": "running",
            "checkpoint_id": run["latest_checkpoint"],
            "prior_trace_id": prior[-1].trace_id,
            "prior_event_id": prior[-1].event_id,
            "reason_source": "deterministic_rule",
        },
    )
    request_events = [e for e in prior if e.event_type == "model.requested"]
    agent.turns = 0
    agent.attempted = store.db.execute(
        "SELECT COUNT(*) FROM tool_calls t JOIN model_requests m ON m.id=t.request_id "
        "WHERE m.run_id=? AND (t.validated_ref IS NOT NULL OR t.rejected=1)",
        (run_id,),
    ).fetchone()[0]
    agent.groups = []
    for event in request_events:
        row = store.db.execute(
            "SELECT * FROM model_requests WHERE id=?", (event.data["request_id"],)
        ).fetchone()
        request = store.blobs.json(row["request_ref"])
        external = request["provider"] != "harness"
        agent.turns += int(external)
        if row["response_ref"] is None:
            if external:
                agent.event(
                    "model.failed",
                    "recovery",
                    {"request_id": row["id"], "reason": "response_not_persisted"},
                )
                agent.event(
                    "retry.decided",
                    "recovery",
                    {
                        "prior_request_id": row["id"],
                        "selected_action": "new_model_attempt",
                        "rule": "recovery.inference-v1",
                    },
                )
                agent.next_model_attempt = request.get("attempt", 1) + 1
                agent.restored_completion = None
            continue
        response = ModelResponse.model_validate_json(store.blobs.read(row["response_ref"]))
        raw = store.blobs.json(response.original_response_ref)
        from local_agent.models.factory import assistant_message, tool_message

        assistant = assistant_message(raw, response)
        group = [assistant]
        image_execution_ids = []
        call_rows = store.db.execute(
            "SELECT * FROM tool_calls WHERE request_id=?", (row["id"],)
        ).fetchall()
        call_rows = sorted(call_rows, key=lambda r: store.blobs.json(r["record_ref"])["index"])
        for call_row in call_rows:
            call = ToolCall.model_validate_json(store.blobs.read(call_row["record_ref"]))
            attempt = store.db.execute(
                "SELECT * FROM execution_attempts WHERE call_id=?", (call.call_id,)
            ).fetchone()
            result = None
            if attempt is not None:
                if attempt["state"] == "finished":
                    result = ExecutionResult.model_validate_json(
                        store.blobs.read(attempt["result_ref"])
                    )
                    execution = ExecutionRequest.model_validate_json(
                        store.blobs.read(attempt["request_ref"])
                    )
                    capture_image(agent, execution, result)
                    await agent.executor.release(attempt["id"])
                else:
                    result = await reconcile(agent, attempt)
                content = result_preview(store, result, call.name)
            elif call_row["rejected"]:
                rejected = next(
                    e
                    for e in prior
                    if e.tool_call_id == call.call_id and e.event_type == "tool.rejected"
                )
                content = {"error": "validation", "detail": rejected.data["error"]}
            else:
                policy_rows = store.db.execute(
                    "SELECT record_ref FROM policy_decisions WHERE call_id=?", (call.call_id,)
                ).fetchall()
                denied = [
                    store.blobs.json(p[0])
                    for p in policy_rows
                    if store.blobs.json(p[0])["verdict"] != "allow"
                ]
                if denied:
                    content = {"error": "policy_denied", "detail": denied[-1]["reason"]}
                else:
                    proposal = next(
                        e
                        for e in prior
                        if e.tool_call_id == call.call_id and e.event_type == "tool.proposed"
                    )
                    content, result = await agent.dispatch(
                        call,
                        proposal,
                        workspace_id=request.get("target_workspace_id"),
                        grant_ref=request.get("workspace_grant_ref"),
                        trusted=not external,
                        resume_validated=bool(call_row["validated_ref"]),
                    )
            if external:
                if (
                    result is not None
                    and result.status == "succeeded"
                    and call.name in ("render_pdf_region", "view_image")
                ):
                    image_execution_ids.append(result.execution_id)
                group.append(tool_message(call, content))
        if external:
            group.extend(
                image_messages(
                    store, agent.run_id, image_execution_ids, agent.config.provider
                )
            )
            agent.groups.append(group)
            agent.restored_completion = None
            if not response.tool_calls:
                agent.completion_response_id = response.request_id
                agent.restored_completion = response.text
    return config
