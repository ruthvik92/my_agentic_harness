"""Readable, read-only run timelines derived from retained evidence."""

from collections import Counter

from local_agent.models.ollama import error_detail


def describe_run(store, run_id, *, action_limit=200):
    row = store.run(run_id)
    manifest = store.blobs.json(row["manifest_ref"])
    config = store.blobs.json(manifest["config_ref"])
    agent = config.get("agent") or {}
    limits = agent.get("limits") or {}
    events = store.events(run_id)
    failed_responses = {e.data.get("request_id"): e.data.get("response_ref") for e in events if e.event_type == "model.failed"}
    requests = {}
    input_tokens = output_tokens = 0
    usage_partial = False
    for request_row in store.db.execute(
        "SELECT id,request_ref,response_ref FROM model_requests WHERE run_id=? ORDER BY rowid",
        (run_id,),
    ):
        request = store.blobs.json(request_row["request_ref"])
        if request.get("provider") == "harness":
            continue
        requests[request_row["id"]] = request
        response = (
            store.blobs.json(request_row["response_ref"]) if request_row["response_ref"] else {}
        )
        usage = response.get("usage") or {}
        if not usage and response.get("original_response_ref"):
            raw = store.blobs.json(response["original_response_ref"])
            usage = raw.get("usage") or raw
        if not usage and failed_responses.get(request_row["id"]):
            try:
                raw = store.blobs.json(failed_responses[request_row["id"]])
                usage = raw.get("usage") or raw
            except (ValueError, TypeError):
                pass
        inp = usage.get("prompt_eval_count", usage.get("prompt_tokens", usage.get("input_tokens")))
        out = usage.get("eval_count", usage.get("completion_tokens", usage.get("output_tokens")))
        if type(inp) is int and inp >= 0:
            input_tokens += inp
        else:
            usage_partial = True
        if type(out) is int and out >= 0:
            output_tokens += out
        else:
            usage_partial = True
    actions = {}
    for call_row in store.db.execute(
        "SELECT id,request_id,record_ref FROM tool_calls WHERE request_id IN (SELECT id FROM model_requests WHERE run_id=?) ORDER BY rowid",
        (run_id,),
    ):
        call = store.blobs.json(call_row["record_ref"])
        if call_row["request_id"] not in requests and call["name"] != "run_command":
            continue
        args = store.blobs.json(call["arguments_ref"])
        actions[call["call_id"]] = {
            "call_id": call["call_id"],
            "tool": call["name"],
            "status": "proposed",
            "path": args.get("path") or args.get("directory") or args.get("cwd"),
            "command": args.get("argv"),
            "actor": "model" if call_row["request_id"] in requests else "controller",
            "cause": "",
            "execution_id": None,
            "exit_code": None,
            "output_available": False,
            "preview_truncated": False,
        }
    stop = None
    provider_errors = []
    test_results = []
    for event in events:
        action = actions.get(event.tool_call_id)
        if (
            event.event_type in {"execution.finished", "execution.reconciled"}
            and action
            and event.data.get("result_ref")
        ):
            result = store.blobs.json(event.data["result_ref"])
            preview = str(result.get("preview", ""))
            cause = ((str(result.get("error") or "") + "\n" + preview).strip()
                     if result.get("status") == "process_limit" else preview)
            action.update(
                status=result["status"],
                execution_id=result["execution_id"],
                exit_code=result.get("exit_code"),
                cause=cause[:2000],
                resource_usage=result.get("resource_usage"),
                output_available=bool(result.get("output_ref")),
                preview_truncated=len(cause) > 2000 or bool(result.get("truncated")),
            )
        elif event.event_type == "tool.rejected" and action:
            action.update(
                status="rejected", cause=str(event.data.get("error", "Tool arguments rejected"))
            )
        elif event.event_type == "policy.evaluated" and action and event.data.get("decision_ref"):
            decision = store.blobs.json(event.data["decision_ref"])
            if decision.get("verdict") == "deny":
                action.update(
                    status="denied", cause=decision.get("reason", "Policy denied this action")
                )
        elif event.event_type == "tool.skipped":
            for call_id in event.data.get("skipped_call_ids", []):
                if call_id in actions:
                    actions[call_id].update(status="skipped", cause=event.data.get("reason", ""))
        elif event.event_type == "model.failed":
            message = event.data.get("detail", "")
            if event.data.get("response_ref"):
                detail = error_detail(store.blobs.read(event.data["response_ref"]))
                if detail and detail not in message:
                    message += ": " + detail
            provider_errors.append({"type": event.data.get("type"), "message": message})
        elif event.event_type == "project.tests":
            report = store.blobs.json(event.data["report_ref"])
            test_results.append(
                {
                    "status": report.get("status"),
                    "error": report.get("error"),
                    "run_id": report.get("run_id"),
                }
            )
        elif event.event_type == "run.stopped":
            stop = event.data.get("reason")
    repair_events = [e for e in events if e.event_type == "repair.progress"]
    repair = None
    if repair_events:
        state = store.blobs.json(repair_events[-1].data["state_ref"])
        repair = {key: state.get(key) for key in ("stage", "decision", "actions", "last_milestone",
                                                 "recoveries", "changed_paths", "monitor_error")}
        repair["mode"] = repair_events[-1].data.get("mode")
    detail = stop.get("detail", "") if isinstance(stop, dict) else str(stop or "")
    values = list(actions.values())
    counts = Counter(a["tool"] for a in values)
    failures = [
        a
        for a in values
        if a["status"] in {"failed", "rejected", "timeout", "output_limit", "process_limit", "cancelled", "denied"}
    ]
    model_limit = limits.get("max_model_turns")
    if (
        detail == "model turns"
        or detail.lower().startswith("model-turn limit")
        or (row["status"] == "budget_exhausted" and model_limit and len(requests) >= model_limit)
    ):
        summary = (
            f"Model-turn limit reached: {len(requests)}"
            + (f"/{model_limit}" if model_limit else "")
            + " model requests. The agent did not finish within this budget."
        )
        if len(values) >= 3 and all(a["tool"] == "list_files" for a in values[-3:]):
            summary += " Its last actions repeatedly listed directories."
    elif detail == "run deadline" or detail.lower().startswith("run time limit"):
        summary = (
            f"Run time limit reached ({limits.get('run_timeout_seconds', 'configured')} seconds)."
        )
    elif detail == "attempted tools" or detail.lower().startswith("tool-call limit"):
        summary = f"Tool-call limit reached (configured cap: {limits.get('max_attempted_tool_calls', 'unknown')})."
    else:
        summary = detail or (
            "The attempt is still running."
            if row["status"] == "running"
            else "Attempt ended: " + row["status"]
        )
    if row["status"] == "budget_exhausted" and not test_results:
        summary += " No independent controller test result was recorded; model-requested commands are listed below."
    return {
        "run_id": run_id,
        "workspace_id": manifest["workspace_id"],
        "status": row["status"],
        "model": agent.get("model"),
        "provider": agent.get("provider"),
        "summary": summary,
        "repair_progress": repair,
        "stop_reason": stop,
        "limits": limits,
        "counts": {
            "model_requests": len(requests),
            "tool_calls": len(values),
            "failed_tools": len(failures),
            "context_compactions": sum(e.event_type == "context.compacted" for e in events),
        },
        "action_counts": dict(counts),
        "actions": values[-action_limit:],
        "actions_omitted": max(0, len(values) - action_limit),
        "failures": failures[-3:],
        "provider_errors": provider_errors,
        "tests": test_results,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "partial": usage_partial,
        },
    }


def execution_output(store, run_id, execution_id, *, related_runs=()):
    row = store.db.execute(
        "SELECT e.result_ref,m.run_id FROM execution_attempts e JOIN tool_calls t ON e.call_id=t.id JOIN model_requests m ON t.request_id=m.id WHERE e.id=?",
        (execution_id,),
    ).fetchone()
    if row is None or row["run_id"] not in {run_id, *related_runs} or not row["result_ref"]:
        raise ValueError("Execution output does not belong to this job")
    result = store.blobs.json(row["result_ref"])
    raw = store.blobs.read(result["output_ref"])
    return {
        "text": raw.decode(errors="replace"),
        "retained_bytes": len(raw),
        "capture_limit_reached": result.get("status") == "output_limit",
        "capture_size_known": result.get("captured_bytes") is not None,
        "preview_was_truncated": bool(result.get("truncated")),
    }


def describe_job(store, job):
    """Attach only check runs referenced by controller-owned evidence."""
    result = describe_run(store, job["run_id"])
    result["job_id"] = job["job_id"]
    result["job_error"] = job.get("error")
    result["loop_id"] = job.get("loop_id")
    related = {t["run_id"] for t in result["tests"] if t.get("run_id")}
    review = job.get("workspace_review") or {}
    controller_tests = review.get("project_tests")
    if controller_tests and not result["tests"]:
        result["tests"].append({"status": controller_tests.get("status"),
                                "error": controller_tests.get("error"),
                                "run_id": controller_tests.get("run_id")})
        result["summary"] = result["summary"].replace(
            " No independent controller test result was recorded; model-requested commands are listed below.",
            " Independent controller checks: " + str(controller_tests.get("status")) + ".",
        )
    related.update(t["run_id"] for t in result["tests"] if t.get("run_id"))
    related.update(review.get("checks_run_ids", []))
    if review.get("checks_run_id"):
        related.add(review["checks_run_id"])
    result["checks"] = []
    for run_id in sorted(related - {job["run_id"]}):
        try:
            check = describe_run(store, run_id)
        except (ValueError, OSError):
            continue
        check["job_id"] = job["job_id"]
        result["checks"].append(check)
    return result
