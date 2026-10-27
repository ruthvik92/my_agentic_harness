"""Validate authoritative events, evidence graphs, and dispatch relationships."""

import json
from collections import Counter

from local_agent.contracts import (
    Checkpoint,
    ContextSnapshot,
    ExecutionRequest,
    ExecutionResult,
    ModelRequest,
    ModelResponse,
    PolicyDecision,
    RunManifest,
    ToolCall,
)
from local_agent.runtime.replay import recorded_replay
from local_agent.storage.blobs import canonical, digest
from local_agent.storage.database import references
from local_agent.tools.registry import normalize


def audit(store, run_id) -> dict:
    errors = []
    visited = set()

    def check_ref(ref):
        if ref in visited:
            return
        visited.add(ref)
        data = store.blobs.read(ref)
        try:
            value = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return
        for nested in references(value):
            check_ref(nested)

    def load(model, ref):
        check_ref(ref)
        return model.model_validate_json(store.blobs.read(ref))

    def checked(label, action):
        try:
            action()
        except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError) as exc:
            errors.append(f"{label}: {exc or 'invariant failed'}")

    run = store.run(run_id)
    manifest = None

    def check_manifest():
        nonlocal manifest
        manifest = load(RunManifest, run["manifest_ref"])
        _require(manifest.run_id == run_id, "manifest run mismatch")
        _require(
            digest(store.blobs.read(manifest.config_ref)) == manifest.config_hash,
            "config hash mismatch",
        )

    checked("manifest", check_manifest)
    events = []
    checked("event schemas", lambda: events.extend(store.events(run_id)))
    seen = set()
    event_index = {}
    for seq, event in enumerate(events, 1):

        def check_event(event=event, seq=seq):
            _require(event.run_seq == seq, "event sequence gap")
            _require(event.run_id == run_id, "event run mismatch")
            _require(all(cause in seen for cause in event.caused_by), "missing or future causal ID")
            for ref in references(event.data):
                check_ref(ref)
            sql = store.db.execute(
                "SELECT run_id,run_seq,event_type FROM events WHERE event_id=?", (event.event_id,)
            ).fetchone()
            _require(
                tuple(sql) == (event.run_id, event.run_seq, event.event_type),
                "event column mismatch",
            )
            causes = {
                row[0]
                for row in store.db.execute(
                    "SELECT cause_id FROM event_causes WHERE event_id=?", (event.event_id,)
                )
            }
            _require(causes == set(event.caused_by), "causal index mismatch")
            if event.event_type == "context.compacted":
                summary = store.blobs.json(event.data["summary_ref"])
                _require(summary["rule"] == event.data["rule"], "compaction rule mismatch")
                _require(
                    set(event.data["inputs"])
                    == {item["source_ref"] for item in summary["omitted"]},
                    "compaction lineage mismatch",
                )
                for item in summary["omitted"]:
                    _require(
                        digest(store.blobs.read(item["source_ref"])) == item["source_hash"],
                        "compaction source hash mismatch",
                    )

        checked(f"event {seq}", check_event)
        seen.add(event.event_id)
        key = (event.event_type, event.tool_call_id)
        event_index.setdefault(key, []).append(event)
    requests = store.db.execute("SELECT * FROM model_requests WHERE run_id=?", (run_id,)).fetchall()
    for row in requests:

        def check_request(row=row):
            request = load(ModelRequest, row["request_ref"])
            _require(
                request.request_id == row["id"] and request.run_id == run_id, "invariant failed"
            )
            snapshot = load(ContextSnapshot, request.context_ref)
            _require(
                digest(store.blobs.read(snapshot.payload_ref)) == snapshot.payload_hash,
                "invariant failed",
            )
            payload = store.blobs.json(snapshot.payload_ref)
            _require(
                canonical({"messages": payload["messages"], "tools": payload.get("tools", [])})
                == canonical({"messages": snapshot.messages, "tools": snapshot.tool_definitions}),
                "context payload mismatch",
            )
            if row["response_ref"]:
                response = load(ModelResponse, row["response_ref"])
                _require(response.request_id == request.request_id, "invariant failed")
                raw = store.blobs.json(response.original_response_ref)
                if "choices" in raw:
                    from local_agent.models.openai import normalize_response

                    raw = normalize_response(raw)
                if "message" in raw:
                    raw = {
                        "text": raw["message"].get("content", ""),
                        "tool_calls": [
                            {
                                "name": call["function"]["name"],
                                "arguments": call["function"]["arguments"],
                                **({"provider_id": call["id"]} if call.get("id") else {}),
                            }
                            for call in raw["message"].get("tool_calls", [])
                        ],
                        "finish_status": "tool_calls"
                        if raw["message"].get("tool_calls")
                        else "stop",
                    }
                _require(
                    canonical(raw.get("tool_calls", []))
                    == canonical(
                        [
                            {
                                k: v
                                for k, v in call.model_dump(mode="json").items()
                                if k != "schema_version"
                                and (not (k == "provider_id" and v is None))
                            }
                            for call in response.tool_calls
                        ]
                    ),
                    "raw provider calls mismatch",
                )
                _require(
                    raw["text"] == response.text and raw["finish_status"] == response.finish_status,
                    "invariant failed",
                )
                calls = store.db.execute(
                    "SELECT record_ref FROM tool_calls WHERE request_id=?", (request.request_id,)
                ).fetchall()
                _require(len(calls) == len(response.tool_calls), "missing proposed calls")
                indices = set()
                for call_row in calls:
                    call = load(ToolCall, call_row[0])
                    _require(call.index not in indices, "duplicate provider call index")
                    indices.add(call.index)
                    original = response.tool_calls[call.index]
                    _require(
                        call.name == original.name and call.provider_id == original.provider_id,
                        "invariant failed",
                    )
                    _require(
                        store.blobs.json(call.arguments_ref) == original.arguments,
                        "invariant failed",
                    )
            else:
                _require(
                    any(event.event_type == "model.failed" for event in events),
                    "pending model request lacks response or failure evidence",
                )

        checked(f"request {row['id']}", check_request)
    calls = store.db.execute(
        "SELECT t.* FROM tool_calls t JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (run_id,),
    ).fetchall()
    for row in calls:

        def check_call(row=row):
            call = load(ToolCall, row["record_ref"])
            _require(
                call.call_id == row["id"] and call.request_id == row["request_id"],
                "invariant failed",
            )
            _require(
                len(event_index.get(("tool.proposed", call.call_id), [])) == 1, "invariant failed"
            )
            if row["validated_ref"]:
                saved = store.blobs.json(row["validated_ref"])
                from local_agent.workspace.options import task_arguments

                config = store.blobs.json(manifest.config_ref)
                request_ref = store.db.execute(
                    "SELECT request_ref FROM model_requests WHERE id=?", (call.request_id,)
                ).fetchone()[0]
                provider = store.blobs.json(request_ref)["provider"]
                arguments = task_arguments(
                    call.name, store.blobs.json(call.arguments_ref),
                    config.get("working_directory", ".") if provider != "harness" else ".",
                )
                normalized = normalize(
                    call.name,
                    arguments,
                    version=call.tool_version,
                    legacy_evidence="evidence_ref" in saved["arguments"],
                )
                _require(
                    canonical(normalized) == store.blobs.read(row["validated_ref"]),
                    "invariant failed",
                )
                _require(
                    len(event_index.get(("tool.validated", call.call_id), [])) == 1,
                    "invariant failed",
                )
            elif row["rejected"]:
                _require(
                    len(event_index.get(("tool.rejected", call.call_id), [])) == 1,
                    "invariant failed",
                )
            elif not any(
                call.call_id in event.data.get("skipped_call_ids", []) for event in events
            ):
                raise ValueError("proposal has no validation, rejection, or visible skipped record")

        checked(f"call {row['id']}", check_call)
    for row in store.db.execute(
        "SELECT p.*,t.validated_ref FROM policy_decisions p JOIN tool_calls t ON t.id=p.call_id "
        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (run_id,),
    ).fetchall():

        def check_policy(row=row):
            decision = load(PolicyDecision, row["record_ref"])
            _require(
                decision.decision_id == row["id"] and decision.call_id == row["call_id"],
                "policy identity mismatch",
            )
            _require(
                decision.normalized_request_ref == row["validated_ref"],
                "policy differs from validated request",
            )
            _require(
                digest(store.blobs.read(row["validated_ref"])) == decision.normalized_request_hash,
                "policy normalized hash mismatch",
            )
            _require(
                decision.policy_hash == store.blobs.json(manifest.config_ref)["policy_hash"],
                "policy differs from effective config",
            )
            matched = event_index.get(("policy.evaluated", decision.call_id), [])
            _require(
                any(event.data["decision_ref"] == row["record_ref"] for event in matched),
                "policy lacks matching event",
            )

        checked(f"policy {row['id']}", check_policy)
    attempts = store.db.execute(
        "SELECT e.*,t.validated_ref,t.record_ref call_ref FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (run_id,),
    ).fetchall()
    for row in attempts:

        def check_dispatch(row=row):
            request = load(ExecutionRequest, row["request_ref"])
            call = load(ToolCall, row["call_ref"])
            policy_row = store.db.execute(
                "SELECT * FROM policy_decisions WHERE id=?", (row["decision_id"],)
            ).fetchone()
            decision = load(PolicyDecision, policy_row["record_ref"])
            _require(
                request.execution_id == row["id"] and request.call_id == row["call_id"],
                "invariant failed",
            )
            _require(request.authorization_ref == decision.decision_id, "invariant failed")
            _require(
                decision.call_id == request.call_id and decision.verdict == "allow",
                "invariant failed",
            )
            expected_workspace = manifest.workspace_id
            if request.workspace_grant_ref:
                grant = store.blobs.json(request.workspace_grant_ref)
                _require(grant["run_id"] == run_id, "grant run mismatch")
                _require(
                    any(
                        event.event_type == "workspace.prepared"
                        and event.data["grant_ref"] == request.workspace_grant_ref
                        for event in events
                    ),
                    "grant missing from audit",
                )
                expected_workspace = grant["workspace_id"]
            _require(
                request.tool == call.name and request.workspace_id == expected_workspace,
                "workspace binding mismatch",
            )
            _require(
                decision.policy_hash == store.blobs.json(manifest.config_ref)["policy_hash"],
                "invariant failed",
            )
            _require(decision.normalized_request_ref == row["validated_ref"], "invariant failed")
            _require(
                digest(store.blobs.read(row["validated_ref"])) == decision.normalized_request_hash,
                "invariant failed",
            )
            _require(
                request.normalized_request_hash == decision.normalized_request_hash,
                "invariant failed",
            )
            normalized = {
                "tool": request.tool,
                "arguments": request.arguments,
                "effective_limits": request.effective_limits.model_dump(mode="json"),
            }
            _require(
                canonical(normalized) == store.blobs.read(row["validated_ref"]), "invariant failed"
            )
            validated = event_index["tool.validated", request.call_id][0]
            policy_event = event_index["policy.evaluated", request.call_id][0]
            intent = event_index["execution.dispatch_intent", request.call_id]
            _require(
                len(intent) == 1 and validated.run_seq < policy_event.run_seq < intent[0].run_seq,
                "invariant failed",
            )
            if row["state"] == "finished":
                result = load(ExecutionResult, row["result_ref"])
                _require(result.execution_id == request.execution_id, "invariant failed")
                output = store.blobs.read(result.output_ref)
                if request.arguments.get("evidence_ref"):
                    from local_agent.runtime.evidence import allowed

                    _require(
                        allowed(store, run_id, request.arguments["evidence_ref"]),
                        "evidence retrieval lacked ownership",
                    )
                    import json

                    slice_data = json.loads(output)
                    source = store.blobs.read(request.arguments["evidence_ref"])
                    offset = request.arguments.get("byte_offset", 0)
                    limit = request.arguments.get("byte_limit", 8192)
                    _require(
                        slice_data["content"]
                        == source[offset : offset + limit].decode(errors="replace"),
                        "evidence slice mismatch",
                    )
                if result.helper_ref:
                    helper = store.blobs.json(result.helper_ref)
                    _require(
                        helper["image"] == manifest.sandbox_image_digest, "helper image mismatch"
                    )
                    _require(result.stdout_ref is not None, "helper lacks captured stdout")
                    header = store.blobs.read(result.stdout_ref).split(b"\n", 1)[0]
                    _require(
                        __import__("json").loads(header[len(b"LOCAL_AGENT_HELPER:") :])
                        == {k: v for k, v in helper.items() if k != "image"},
                        "helper header mismatch",
                    )
                _require(
                    output.decode("utf-8", errors="replace").startswith(result.preview),
                    "preview differs from evidence",
                )
                _require(
                    len(event_index.get(("execution.finished", request.call_id), []))
                    + len(
                        [
                            event
                            for event in event_index.get(
                                ("execution.reconciled", request.call_id), []
                            )
                            if event.data.get("result_ref")
                        ]
                    )
                    == 1,
                    "invariant failed",
                )
            else:
                raise ValueError(f"pending dispatch requires reconciliation: {row['state']}")

        checked(f"execution {row['id']}", check_dispatch)
    for row in store.db.execute("SELECT * FROM checkpoints WHERE run_id=?", (run_id,)):

        def check_checkpoint(row=row):
            checkpoint = load(Checkpoint, row["record_ref"])
            _require(
                checkpoint.checkpoint_id == row["id"] and checkpoint.run_id == run_id,
                "invariant failed",
            )
            _require(checkpoint.completed_event_seq == row["event_seq"], "invariant failed")
            _require(checkpoint.workspace_id == manifest.workspace_id, "invariant failed")

        checked(f"checkpoint {row['id']}", check_checkpoint)
    checked(
        "foreign keys",
        lambda: _require(
            not store.db.execute("PRAGMA foreign_key_check").fetchall(), "foreign key violation"
        ),
    )

    def check_replay():
        replay = recorded_replay(store, run_id)
        _require(replay["status"] == run["status"], "event/state terminal mismatch")
        if run["status"] == "verified":
            verified = [
                event
                for event in events
                if event.event_type == "completion.verified" and event.data.get("passed")
            ]
            _require(bool(verified) and manifest.mode == "live", "missing real verification")
            event = verified[-1]
            result = load(ExecutionResult, event.data["result_ref"])
            _require(
                result.exit_code == 0 and result.status == "succeeded" and not result.simulated,
                "verification did not pass",
            )
            _require(
                event.data["workspace_id"] != manifest.workspace_id,
                "verification must use a clean workspace",
            )
            execution = store.db.execute(
                "SELECT request_ref,result_ref FROM execution_attempts WHERE id=?",
                (result.execution_id,),
            ).fetchone()
            _require(
                execution is not None and execution["result_ref"] == event.data["result_ref"],
                "verification result is not committed",
            )
            request = load(ExecutionRequest, execution["request_ref"])
            grant = store.blobs.json(request.workspace_grant_ref)
            _require(grant["purpose"] == "verification", "verification grant mismatch")
        if run["status"] == "completed_unverified":
            _require(any(e.event_type == "completion.proposed" for e in events), "invariant failed")

    checked("recorded state", check_replay)
    return {
        "run_id": run_id,
        "ok": not errors,
        "errors": errors,
        "events": len(events),
        "checked_blobs": len(visited),
        "event_counts": dict(Counter(e.event_type for e in events)),
    }


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)
