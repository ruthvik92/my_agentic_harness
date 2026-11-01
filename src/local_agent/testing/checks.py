"""Independent checks shared by coding completion and workspace review."""

import json
from pathlib import Path

from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.observability.spans import Spans
from local_agent.testing.environment import prepare_environment
from local_agent.testing.runner import arguments


def changed_files(project, baseline):
    from local_agent.workspace.manager import IMPORT_EXCLUDES

    def files(root):
        result = {}
        for path in Path(root).rglob("*"):
            relative = path.relative_to(root)
            if any(
                part in IMPORT_EXCLUDES or part.endswith(".egg-info") for part in relative.parts
            ):
                continue
            if path.is_file() and not path.is_symlink():
                result[str(relative)] = path.read_bytes()
        return result

    before, after = files(baseline), files(project)
    return sorted(
        name for name in before.keys() | after.keys() if before.get(name) != after.get(name)
    )


async def run_checks(store, config, project, plan, sandbox, *, locked=False):
    # Nested checks share the parent's serialized SQLite connection. Opening a second
    # writable Store would close an extra raw database fd and can release POSIX locks.
    # Evidence budgets still belong to individual runs, so restore the parent's budget.
    budget, refs = store.blobs.budget, store.blobs.budget_refs
    spans = Spans()
    try:
        # Preparation can fail before Agent.run opens its recording span.
        with spans.boundary("project.checks"):
            return await _run_checks(store, config, project, plan, sandbox, locked=locked)
    finally:
        store.blobs.budget, store.blobs.budget_refs = budget, refs
        spans.shutdown()


async def _run_checks(store, config, project, plan, sandbox, *, locked=False):
    from local_agent.runtime.agent import Agent

    try:
        prepared = await prepare_environment(store.root, project, plan, sandbox)
    except (RuntimeError, ValueError, OSError) as exc:
        from local_agent.contracts import RunManifest, new_id
        from local_agent.storage.blobs import digest

        run_id = new_id("run")
        ref = store.blobs.put_json(
            {
                "agent": config.model_dump(mode="json"),
                "sandbox": sandbox,
                "task": "Prepare project test environment",
            }
        )
        store.create_run(
            RunManifest(
                run_id=run_id,
                thread_id=new_id("thread"),
                workspace_id=new_id("ws"),
                config_ref=ref,
                config_hash=digest(store.blobs.read(ref)),
                model_identity="controller-test-setup",
                sandbox_image_digest=sandbox["image"],
                mode="live",
                package_versions={},
            )
        )
        store.transition(run_id, "running")
        report = {
            "status": "environment_blocked",
            "error": str(exc),
            "commands": [],
            "plan": plan,
            "run_id": run_id,
        }
        store.append(
            run_id, "project.tests", "controller", {"report_ref": store.blobs.put_json(report)}
        )
        store.transition(
            run_id, "failed", reason={"type": "TestEnvironmentBlocked", "detail": str(exc)}
        )
        checked = audit(store, run_id)
        report["audit"] = checked
        return report, {"run_id": run_id, "status": "failed", "error": str(exc)}, sandbox
    from local_agent.config import instruction_text
    from local_agent.storage.blobs import digest

    steps = [{**plan, "commands": [command]} for command in plan["commands"]] or [plan]
    expected = [arguments(step)["argv"] for step in steps]
    cfg = config.model_copy(
        update={
            "instructions_version": "project-tests-v1",
            "instructions_hash": digest(instruction_text("project-tests-v1").encode()),
            "provider": "ollama",
            "model": "scripted-project-checks",
            "reasoning_effort": None,
            "tools": ("run_command",),
            "project_tests": False,
            # Disposable check copies must not consume persistent workspace capacity.
            "execution": config.execution.model_copy(update={"execution_mode_default": "ephemeral"}),
            "limits": config.limits.model_copy(
                update={"max_model_turns": 2, "max_attempted_tool_calls": len(steps) + 4}
            ),
        }
    )
    script = ScriptedProvider(
        [
            {
                "text": "Run the project test plan.",
                "tool_calls": [
                    {"name": "run_command", "arguments": arguments(step)} for step in steps
                ],
                "finish_status": "tool_calls",
            },
            {
                "text": "Project check execution recorded.",
                "tool_calls": [],
                "finish_status": "stop",
            },
        ]
    )
    agent = Agent(store, cfg, prepared, provider=script)
    # A coding parent already holds the data-root lease. The child shares that lease and Store.
    result = (
        await agent._run(project, "Execute the frozen project test plan.")
        if locked
        else await agent.run(project, "Execute the frozen project test plan.")
    )
    checked = audit(store, result["run_id"])
    report = {
        "status": "environment_blocked",
        "error": result.get("error"),
        "commands": [],
        "plan": plan,
        "run_id": result["run_id"],
        "audit": checked,
        "environment": prepared.get("test_environment"),
    }
    matched = 0
    failures = []
    for event in store.events(result["run_id"]):
        if event.event_type != "execution.finished":
            continue
        outcome = store.blobs.json(event.data["result_ref"])
        if not outcome.get("command") or list(outcome["command"]) not in expected:
            continue
        matched += 1
        try:
            parsed = json.loads(
                store.blobs.read(outcome.get("stdout_ref") or outcome["output_ref"])
            )
            report["commands"].extend(
                {
                    **item,
                    "output_ref": outcome["output_ref"],
                    "execution_id": outcome["execution_id"],
                }
                for item in parsed["commands"]
            )
            if report.get("setup") is None:
                report["setup"] = parsed.get("setup")
            if parsed["status"] != "passed":
                failures.append(parsed["status"])
                report["error"] = parsed.get("error")
            report["status"] = failures[0] if failures else "passed"
        except (ValueError, UnicodeError):
            failures.append("timeout" if outcome["status"] == "timeout" else "environment_blocked")
            report.update(
                status="timeout" if outcome["status"] == "timeout" else "environment_blocked",
                error=outcome.get("preview", "Test runner returned no structured report"),
            )
        report.update(
            execution_id=outcome["execution_id"],
            output_ref=outcome["output_ref"],
            exit_code=outcome["exit_code"],
        )
    if result["status"] != "completed_unverified" or not checked["ok"] or matched != len(steps):
        report["status"] = "environment_blocked"
    return report, result, prepared
