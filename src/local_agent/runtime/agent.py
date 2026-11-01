"""Single-agent live runtime. Every operation uses the existing durable protocol."""

import asyncio
import json
import time
from collections import Counter
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_agent.config import instruction_text
from local_agent.contracts import (
    ArtifactRecord,
    Checkpoint,
    ExecutionRequest,
    ModelRequest,
    ModelResponse,
    RunManifest,
    ToolCall,
    new_id,
)
from local_agent.executor.docker import DockerExecutor
from local_agent.models.factory import assistant_message, create_provider, tool_message
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.spans import Spans, correlation
from local_agent.policy.engine import OFFLINE_HASH, OFFLINE_POLICY, offline_evaluate
from local_agent.runtime.context import ContextBuilder
from local_agent.runtime.image_capture import capture_image
from local_agent.runtime.image_messages import image_messages
from local_agent.runtime.tool_results import result_preview
from local_agent.storage.blobs import canonical, digest, private_directory
from local_agent.storage.database import AuditUnavailable
from local_agent.tools.guidance import GUIDE, correction
from local_agent.tools.registry import VERSIONS, normalize
from local_agent.workspace.manager import IMPORT_EXCLUDES, Workspaces, copy_tree

BOOTSTRAP = """import subprocess
for argv in [['git','init'],['git','add','.'],['git','-c','user.name=Local Agent','-c',
 'user.email=local-agent@localhost','commit','--allow-empty','-m','baseline']]:
 subprocess.run(argv,check=True)
"""
DIFF = """import os,shutil,subprocess
for argv in [['git','init'],['git','add','.'],['git','-c','user.name=Local Agent','-c',
 'user.email=local-agent@localhost','commit','--allow-empty','-qm','baseline']]:
 subprocess.run(argv,check=True,stdout=subprocess.DEVNULL)
for name in os.listdir('.'):
 if name != '.git':
  if os.path.isdir(name) and not os.path.islink(name): shutil.rmtree(name)
  else: os.unlink(name)
shutil.copytree('/workspace/scratch/candidate','.',dirs_exist_ok=True,symlinks=False)
subprocess.run(['git','add','-N','.'],check=True)
subprocess.run(['git','diff','--no-ext-diff','--no-textconv','HEAD'],check=True)
"""


class BudgetExhausted(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class Agent:
    def __init__(
        self,
        store,
        config,
        sandbox,
        *,
        provider=None,
        capability_report=None,
        fault_hook=None,
        workspace_options=None,
        progress_path=None,
        expected_workspace=None,
        expected_attempt=None,
    ):
        self.store, self.config, self.sandbox = store, config, sandbox
        self.base_sandbox = sandbox
        self.progress_path = progress_path
        self.expected_workspace = expected_workspace
        self.expected_attempt = expected_attempt
        self.test_plan = None
        self.test_retries = 0
        self.project_test_report = None
        self.environment_inventory = None
        self.workspaces = Workspaces(store.root)
        self.provider = provider or create_provider(store.blobs, config)
        self.executor = DockerExecutor(
            store, self.workspaces, sandbox["image"], settings=config.execution
        )
        self.spans = Spans()
        self.context = ContextBuilder(store.blobs, config)
        self.turns = self.attempted = 0
        self.groups = []
        self.failures = Counter()
        self.policy_hash = OFFLINE_HASH
        self.run_id = new_id("run")
        self.last = None
        self.deadline = time.monotonic() + config.limits.run_timeout_seconds
        self.created = False
        self.capability_report = capability_report
        self.fault_hook = fault_hook
        self.current_external = False
        self.executor.fault_hook = self.fault
        self.restored_completion = None
        self.completion_response_id = None
        self.instructions = instruction_text(config.instructions_version)
        self.verifier = "calculator"
        self.next_model_attempt = 1
        from local_agent.workspace.options import validate_options

        self.workspace_options = validate_options(workspace_options or {})
        self.working_directory = self.workspace_options.get("working_directory", ".")

    async def run(self, source, task, *, verify_fixture=False, probe=False, resume_run_id=None):
        from local_agent.storage.locks import run_lock

        try:
            with run_lock(self.store.control):
                result = await self._run(
                    source,
                    task,
                    verify_fixture=verify_fixture,
                    probe=probe,
                    resume_run_id=resume_run_id,
                )
                if hasattr(self, "workspace_id"):
                    result["working_directory"] = self.working_directory
                    result["task_mode"] = (
                        "continue" if self.workspace_options.get("continue_workspace_id") else "new"
                    )
                    git_workspace = self.workspaces.git_info(self.workspace_id)
                    if git_workspace:
                        result["git_workspace"] = git_workspace
                        result["workspace"] = str(self.path)
                return result
        except RuntimeError:
            if hasattr(self.provider, "close"):
                await self.provider.close()
            self.spans.shutdown()
            raise

    async def prepare(self):
        pass

    def check_paid_budget(self, snapshot):
        if self.config.provider != "openai" or self.config.paid_token_limit is None:
            return
        used = 0
        for row in self.store.db.execute("SELECT request_ref,response_ref FROM model_requests WHERE run_id=?", (self.run_id,)):
            if self.store.blobs.json(row[0]).get("provider") != "openai":
                continue
            if row[1] is None:
                raise BudgetExhausted("Paid usage is unknown after an incomplete request; automatic paid retry stopped")
            response = self.store.blobs.json(row[1])
            usage = response.get("usage") or {}
            inp = usage.get("prompt_tokens", usage.get("input_tokens"))
            out = usage.get("completion_tokens", usage.get("output_tokens"))
            if type(inp) is not int or type(out) is not int or inp < 0 or out < 0:
                raise BudgetExhausted("Paid usage is unknown; automatic paid calls stopped")
            used += inp + out
        if used + snapshot.token_estimate + self.config.output_reserve_tokens > self.config.paid_token_limit:
            raise BudgetExhausted("Paid token allowance cannot cover the next request and reserved output")

    @asynccontextmanager
    async def frozen_workspace(self, workspace_id=None):
        from local_agent.executor.maintenance import cleanup_attestor

        manager = self.executor.make_manager(lambda *_: None)
        manager.attest = cleanup_attestor(self.store, self.workspaces)
        async with manager.snapshot(workspace_id or self.workspace_id):
            yield

    async def before_model(self):
        """Subclass controller checks at a completed-exchange boundary."""

    def fixed_messages(self, task):
        messages = [{"role": "system", "content": self.instructions}]
        if self.config.instructions_version.startswith("coder-"):
            messages.append(self.directory_message())
            messages.append({"role": "system", "content": GUIDE})
            if "prepare_environment" in self.config.tools:
                messages.append({"role": "system", "content":
                    "Inspect the environment inventory before execution. Request missing tooling with "
                    "prepare_environment instead of repeatedly importing missing packages. Preparation "
                    "restarts processes and preserves project files; execution stays offline. A response "
                    "with status environment_blocked is a setup limitation, not a passing test. "
                    "Do not repeat unchanged failed requests. Installed inventory: "
                    + canonical(self.environment_inventory or {"status": "not probed"}).decode()})
        if self.test_plan is not None:
            if self.project_test_report and self.project_test_report.get("status") == "environment_blocked":
                messages.append({"role": "system", "content":
                    "Automatic test environment preparation was blocked: "
                    + str(self.project_test_report.get("error", "unknown setup error"))
                    + ". Inspect requirements and request a suitable environment before implementation."})
            messages.append(
                {
                    "role": "system",
                    "content": "Use test-driven development: write regression tests first, run them to demonstrate failure, then implement and rerun. Run the shared offline test plan with run_command argv=['python','/workspace/tools/test_project.py']. The controller independently reruns it before completion. Plan: "
                    + canonical(self.test_plan).decode(),
                }
            )
        from local_agent.runtime.capability_failures import fixed_context

        capability_context = fixed_context(self) if self.created else None
        if capability_context:
            messages.append(capability_context)
        return [*messages, {"role": "user", "content": task}]

    def directory_message(self):
        prefix = "project" if self.working_directory == "." else "project/" + self.working_directory
        return {
            "role": "system",
            "content": (
                f"Task working directory: {prefix}. Start by listing this directory. "
                "For files named in the task, use this directory as the base. File tool paths "
                "remain workspace-relative: include the full prefix above. Commands and git_diff "
                "default to this directory when cwd is omitted. This is task focus, not a permission boundary."
            ),
        }

    async def complete(self, answer, verify_fixture):
        row = self.store.db.execute(
            "SELECT response_ref FROM model_requests WHERE id=?", (self.completion_response_id,)
        ).fetchone()
        proposed = any(
            event.event_type == "completion.proposed" and event.data.get("response_ref") == row[0]
            for event in self.store.events(self.run_id)
        )
        if not proposed:
            self.event("completion.proposed", "model", {"response_ref": row[0]})
        if verify_fixture:
            passed, content = await self.verify()
            if not passed:
                self.groups.append(
                    [
                        {
                            "role": "user",
                            "content": "Independent verification failed. Repair the implementation. Evidence: "
                            + canonical(content).decode(),
                        }
                    ]
                )
                self.checkpoint()
                return None
        if self.test_plan is not None:
            from local_agent.testing.checks import changed_files, run_checks
            from local_agent.testing.plans import resolve, seal

            plan = (
                resolve(self.path / "project", self.working_directory, discover_contract=False)
                if self.test_plan["origin"] == "automatic Python detection"
                else dict(self.test_plan)
            )
            changes = changed_files(self.path / "project", self.baseline)
            changed_tests = [
                name
                for name in changes
                if Path(name).name.startswith("test_")
                and name.endswith(".py")
                and (self.path / "project" / name).is_file()
            ]
            if (
                plan["origin"] == "automatic Python detection"
                and changed_tests
                and self.working_directory == "."
            ):
                plan["commands"].append(
                    {"argv": ["python", "-m", "pytest", "-q", *changed_tests], "cwd": "."}
                )
            plan = seal(plan)
            try:
                report, _, _ = await run_checks(
                    self.store,
                    self.config,
                    self.path / "project",
                    plan,
                    self.sandbox,
                    locked=True,
                )
            except (RuntimeError, ValueError) as exc:
                report = {
                    "status": "environment_blocked",
                    "error": str(exc),
                    "commands": [],
                    "plan": plan,
                }
            code_changed = any(
                name.endswith(".py") and not Path(name).name.startswith("test_") for name in changes
            )
            if code_changed and not changed_tests and report["status"] == "passed":
                report["status"] = "tests_required"
                report["error"] = "Add regression tests for the implementation changes."
            self.project_test_report = report
            self.event(
                "project.tests", "controller", {"report_ref": self.store.blobs.put_json(report)}
            )
            if (
                report["status"] != "passed"
                and self.test_retries < 2
                and self.turns < self.config.limits.max_model_turns
            ):
                self.test_retries += 1
                self.groups.append(
                    [
                        {
                            "role": "user",
                            "content": "Controller test plan failed. Follow test-driven development: add regression tests, reproduce the failure, then repair implementation. Actual evidence: "
                            + canonical(report).decode()[:12000],
                        }
                    ]
                )
                self.checkpoint()
                return None
        diff_ref = await self.final_diff()
        if self.workspaces.git_info(self.workspace_id):
            from local_agent.workspace.git import GitWorktrees

            _, diff_workspace_id = self.cached_trusted("final_diff")
            snapshot = self.workspaces.path(diff_workspace_id) / "scratch" / "candidate"
            git_workspace = GitWorktrees(self.workspaces).finalize(self.workspace_id, snapshot)
            self.event("workspace.prepared", "host-git", {"git_workspace": git_workspace})
        status = "verified" if verify_fixture else "completed_unverified"
        self.last = self.store.transition(self.run_id, status, causes=(self.last.event_id,))
        return {
            "run_id": self.run_id,
            "status": status,
            "answer": answer,
            "workspace": str(self.path),
            "diff_ref": diff_ref,
            **({"repair_progress": self.repair_guard.public()}
               if getattr(self, "repair_guard", None) else {}),
            **(
                {"project_tests": self.project_test_report}
                if self.project_test_report is not None
                else {}
            ),
        }

    def cached_trusted(self, purpose):
        from local_agent.contracts import ExecutionResult

        rows = self.store.db.execute(
            "SELECT e.request_ref,e.result_ref,m.request_ref model_ref FROM execution_attempts e "
            "JOIN tool_calls t ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id "
            "WHERE m.run_id=? AND e.state='finished'",
            (self.run_id,),
        ).fetchall()
        for row in reversed(rows):
            request = self.store.blobs.json(row["model_ref"])
            execution = self.store.blobs.json(row["request_ref"])
            grant_ref = execution.get("workspace_grant_ref")
            if request["provider"] == "harness" and request["purpose"] == purpose and grant_ref:
                grant = self.store.blobs.json(grant_ref)
                if grant.get("stage_id") == self.completion_response_id:
                    return ExecutionResult.model_validate_json(
                        self.store.blobs.read(row["result_ref"])
                    ), grant["workspace_id"]
        return None

    def fault(self, point):
        if self.fault_hook and self.current_external:
            self.fault_hook(point)

    def check(self, *, model=False, call=False):
        if (
            self.created
            and self.store.db.execute(
                "SELECT 1 FROM events WHERE run_id=? AND event_type='cancel.requested' LIMIT 1",
                (self.run_id,),
            ).fetchone()
        ):
            raise RunCancelled("cancellation requested")
        if time.monotonic() >= self.deadline:
            raise BudgetExhausted(f"Run time limit reached ({self.config.limits.run_timeout_seconds} seconds)")
        if model and self.turns >= self.config.limits.max_model_turns:
            raise BudgetExhausted(f"Model-turn limit reached: {self.turns}/{self.config.limits.max_model_turns} model requests; the agent did not complete within this budget")
        if call and self.attempted >= self.config.limits.max_attempted_tool_calls:
            raise BudgetExhausted(f"Tool-call limit reached: {self.attempted}/{self.config.limits.max_attempted_tool_calls} attempted calls")

    def event(self, kind, actor, data):
        self.last = self.store.append(
            self.run_id, kind, actor, data, causes=(self.last.event_id,) if self.last else ()
        )
        if self.progress_path is not None and self.created:
            from local_agent.executor.lifecycle import publish

            publish(Path(self.progress_path), {"run_id": self.run_id, "phase": kind})
        return self.last

    def request(
        self, snapshot_ref, *, provider=None, purpose="agent", workspace_id=None, grant_ref=None
    ):
        ctx = correlation()
        request = ModelRequest(
            request_id=new_id("req"),
            run_id=self.run_id,
            context_ref=snapshot_ref,
            provider=provider
            or (
                "scripted" if isinstance(self.provider, ScriptedProvider) else self.config.provider
            ),
            model=self.config.model,
            purpose=purpose,
            attempt=self.next_model_attempt if provider != "harness" else 1,
            target_workspace_id=workspace_id,
            workspace_grant_ref=grant_ref,
            options=self.store.blobs.json(self.store.blobs.json(snapshot_ref)["payload_ref"]).get(
                "options", {}
            ),
            deadline_utc=(
                datetime.now(UTC) + timedelta(seconds=max(0, self.deadline - time.monotonic()))
            ).isoformat(),
            trace_id=ctx["trace_id"],
            parent_span_id=ctx["span_id"],
        )
        self.last = self.store.record_request(request, causes=(self.last.event_id,))
        self.current_external = request.provider != "harness"
        if self.current_external:
            self.next_model_attempt = 1
            self.fault("after_model_request")
        return request

    def response(self, request, response):
        if isinstance(response, dict):
            response = ModelResponse.model_validate_json(
                canonical(
                    {
                        **response,
                        "request_id": request.request_id,
                        "original_response_ref": self.store.blobs.put_json(response),
                    }
                )
            )
        calls = tuple(
            ToolCall(
                call_id=new_id("call"),
                request_id=request.request_id,
                index=index,
                provider_id=call.provider_id,
                name=call.name,
                tool_version=VERSIONS.get(call.name, 1),
                arguments_ref=self.store.blobs.put_json(call.arguments),
            )
            for index, call in enumerate(response.tool_calls)
        )
        self.last, proposals = self.store.record_response(
            self.run_id, response, calls, causes=(self.last.event_id,)
        )
        self.current_external = request.provider != "harness"
        self.fault("after_response_persistence")
        return response, calls, proposals

    async def dispatch(
        self,
        call,
        proposal,
        *,
        workspace_id=None,
        grant_ref=None,
        trusted=False,
        resume_validated=False,
    ):
        self.check(call=not resume_validated)
        self.attempted += int(not resume_validated)
        with self.spans.boundary("tool.validate"):
            try:
                saved = self.store.db.execute(
                    "SELECT validated_ref FROM tool_calls WHERE id=?", (call.call_id,)
                ).fetchone()
                legacy = bool(
                    saved[0] and "evidence_ref" in self.store.blobs.json(saved[0])["arguments"]
                )
                arguments = self.store.blobs.json(call.arguments_ref)
                if not trusted:
                    from local_agent.workspace.options import task_arguments

                    arguments = task_arguments(call.name, arguments, self.working_directory)
                normalized = normalize(
                    call.name,
                    arguments,
                    version=call.tool_version,
                    legacy_evidence=legacy,
                    pids_limit=self.config.execution.container_pids_limit,
                )
                error = None
            except ValueError as exc:
                normalized, error = None, str(exc)
            if not resume_validated:
                self.last = self.store.record_validation(
                    self.run_id, call.call_id, normalized, error, causes=(proposal.event_id,)
                )
            else:
                self.event(
                    "retry.decided",
                    "recovery",
                    {
                        "call_id": call.call_id,
                        "selected_action": "revalidate_current_policy",
                        "rule": "recovery.undispatched-v1",
                    },
                )
        if normalized is None:
            key = digest(canonical({"name": call.name, "arguments_ref": call.arguments_ref}))
            self.failures[key] += 1
            if self.failures[key] >= self.config.limits.max_identical_failures:
                raise BudgetExhausted("three identical schema rejections: " + call.name + " — " + correction(call.name, arguments, error))
            return {"error": "validation", "detail": error, "correction": correction(call.name, arguments, error)}, None
        with self.spans.boundary("policy.evaluate"):
            decision = offline_evaluate(
                call.call_id,
                normalized,
                self.store.blobs.put_json(normalized),
                (call.name,) if trusted else self.config.tools,
                policy_hash=self.policy_hash,
            )
            if call.name == "read_file" and normalized["arguments"].get("evidence_ref") is not None:
                from local_agent.runtime.evidence import allowed

                if not allowed(self.store, self.run_id, normalized["arguments"]["evidence_ref"]):
                    decision = decision.model_copy(
                        update={
                            "verdict": "deny",
                            "reason": "Evidence reference is not produced by this run.",
                        }
                    )
            self.last = self.store.record_policy(
                self.run_id, decision, causes=(self.last.event_id,)
            )
        if decision.verdict != "allow":
            self.failures[decision.normalized_request_hash] += 1
            if (
                self.failures[decision.normalized_request_hash]
                >= self.config.limits.max_identical_failures
            ):
                raise BudgetExhausted("three identical policy denials")
            return {"error": "policy_denied", "detail": decision.reason}, None
        if call.name == "run_command" and not trusted:
            from local_agent.runtime.capability_failures import cached

            fact = cached(self, normalized["arguments"])
            if fact:
                preview = {"status": "environment_blocked", "executed": False,
                           "error": "unchanged_unavailable_capability", "failure": fact["failure"],
                           "evidence_ref": fact["output_ref"], "correction": fact["correction"]}
                self.event("tool.skipped", "controller", {
                    "skipped_call_ids": [call.call_id], "reason": "unchanged_unavailable_capability",
                    "preview_ref": self.store.blobs.put_json(preview),
                })
                return preview, None
        with self.spans.boundary("tool.execute"):
            ctx = correlation()
            execution = ExecutionRequest(
                execution_id=new_id("exec"),
                call_id=call.call_id,
                workspace_id=workspace_id or self.workspace_id,
                workspace_grant_ref=grant_ref,
                tool=call.name,
                tool_version=call.tool_version,
                arguments=normalized["arguments"],
                effective_limits=normalized["effective_limits"],
                authorization_ref=decision.decision_id,
                normalized_request_hash=decision.normalized_request_hash,
                trace_id=ctx["trace_id"],
                parent_span_id=ctx["span_id"],
                deadline_utc=(
                    datetime.now(UTC) + timedelta(seconds=max(0, self.deadline - time.monotonic()))
                ).isoformat(),
            )
            self.last = self.store.commit_dispatch(
                self.run_id, execution, causes=(self.last.event_id,)
            )
            self.fault("after_dispatch_intent")
            self.last = self.store.execution_event(
                self.run_id, execution.execution_id, causes=(self.last.event_id,)
            )
            if call.name in {"environment_inventory", "prepare_environment"}:
                from local_agent.environments.service import execute as environment_execute

                result = await environment_execute(self, execution)
            elif call.name == "read_file" and execution.arguments.get("evidence_ref"):
                from local_agent.runtime.evidence import execute as read_evidence

                result = read_evidence(self.store, self.run_id, execution)
            else:
                mode = "ephemeral" if trusted else self.config.execution.execution_mode_default
                if mode == "persistent":
                    from local_agent.executor.maintenance import ensure_reaper

                    ensure_reaper(self.store.root, self.sandbox["image"], self.config.execution)
                result = await self.executor.execute(execution, execution_mode=mode)
            capture_image(self, execution, result)
            self.last = self.store.execution_event(
                self.run_id, execution.execution_id, result, causes=(self.last.event_id,)
            )
            self.fault("after_result_commit")
            if call.name not in {"environment_inventory", "prepare_environment"}:
                await self.executor.release(execution.execution_id)
            preview = result_preview(self.store, result, call.name)
            preparation_ready = (call.name == "prepare_environment" and result.output_ref
                                 and self.store.blobs.json(result.output_ref).get("status") == "ready")
            if result.status == "succeeded" and (call.name in {"write_file", "patch_file", "execute_tool"} or preparation_ready):
                from local_agent.runtime.capability_failures import invalidate

                invalidate(self, "successful tool may have changed workspace dependencies")
            if (not trusted and result.status == "succeeded" and call.name in {"write_file", "patch_file"}
                    and str(arguments.get("path", "")).startswith("project/")):
                try:
                    change = json.loads(result.preview)
                    if change.get("content_hash") and change["content_hash"] != change.get("previous_hash"):
                        # A new code state deserves a new reproduction attempt. Unchanged
                        # writes and failed edits never reset the repeated-failure guard.
                        self.failures.clear()
                except (ValueError, TypeError):
                    pass
            if call.name == "run_command" and not trusted:
                from local_agent.runtime.capability_failures import diagnose, guidance, record

                output = result.preview
                if result.output_ref:
                    output = self.store.blobs.read(result.output_ref)[:65536].decode("utf-8", errors="replace")
                failure = diagnose(result.status, result.exit_code, output, result.error)
                record(self, normalized["arguments"], result, failure)
                if failure["kind"] != "none":
                    preview["failure"] = failure
                    preview["correction"] = guidance(failure, self.environment_inventory)
            elif result.status != "succeeded" and not trusted:
                preview["correction"] = correction(call.name, arguments, str(preview))
            if result.status != "succeeded":
                self.failures[decision.normalized_request_hash] += 1
                if (
                    self.failures[decision.normalized_request_hash]
                    >= self.config.limits.max_identical_failures
                ):
                    detail = ""
                    if result.status == "process_limit":
                        detail = ": " + result.error
                    if call.name in {"patch_file", "write_file", "read_file"}:
                        try:
                            error = json.loads(preview.get("preview", ""))
                            detail = ": " + str(error.get("detail", error.get("error", "")))[:300]
                        except (ValueError, TypeError):
                            pass
                    raise BudgetExhausted(
                        "three identical failed actions: " + call.name
                        + (" for " + str(arguments["path"]) if "path" in arguments else "")
                        + detail
                    )
            return preview, result

    async def trusted(self, name, arguments, purpose, workspace_id=None, grant_ref=None):
        fixed = [
            {
                "role": "system",
                "content": f"Deterministic harness operation: {purpose}. No model inference.",
            }
        ]
        snapshot, ref = ContextBuilder(
            self.store.blobs, self.config.model_copy(update={"tools": (name,)})
        ).build(fixed, [])
        self.event("context.built", "runtime", {"snapshot_ref": ref, "purpose": purpose})
        request = self.request(
            ref, provider="harness", purpose=purpose, workspace_id=workspace_id, grant_ref=grant_ref
        )
        response, calls, proposals = self.response(
            request,
            {
                "text": "Trusted fixed operation.",
                "tool_calls": [{"name": name, "arguments": arguments}],
                "finish_status": "tool_calls",
            },
        )
        return await self.dispatch(
            calls[0], proposals[0], workspace_id=workspace_id, grant_ref=grant_ref, trusted=True
        )

    def grant(self, workspace_id, purpose):
        ref = self.store.blobs.put_json(
            {
                "run_id": self.run_id,
                "workspace_id": workspace_id,
                "purpose": purpose,
                "policy_hash": OFFLINE_HASH,
                "stage_id": self.completion_response_id,
            }
        )
        self.event("workspace.prepared", "workspace", {"grant_ref": ref})
        return ref

    async def verify(self):
        cached = self.cached_trusted("verification")
        if cached:
            result, workspace_id = cached
            from local_agent.runtime.recovery import preview as result_preview

            preview = result_preview(result)
        else:
            workspace_id, _ = self.workspaces.create(self.path / "project")
            grant = self.grant(workspace_id, "verification")
            preview, result = await self.trusted(
                "run_command",
                {"argv": ["python", "-I", "/opt/local-agent/verify.py", self.verifier]},
                "verification",
                workspace_id,
                grant,
            )
        passed = False
        if result is not None and result.exit_code == 0 and not result.truncated:
            try:
                passed = json.loads(result.preview).get("verified") is True
            except ValueError:
                pass
        self.event(
            "completion.verified",
            "verifier",
            {
                "passed": passed,
                "execution_id": result.execution_id if result else None,
                "result_ref": self.store.blobs.put_json(result) if result else None,
                "workspace_id": workspace_id,
                "verifier_hash": self.sandbox["verifier_hash"],
            },
        )
        return passed, preview

    async def final_diff(self):
        cached = self.cached_trusted("final_diff")
        if cached:
            result, workspace_id = cached
        else:
            workspace_id, root = self.workspaces.create(self.baseline)
            copy_tree(
                self.path / "project",
                root / "scratch" / "candidate",
                exclude=IMPORT_EXCLUDES,
            )
            grant = self.grant(workspace_id, "final_diff")
            _, result = await self.trusted(
                "run_command",
                {"argv": ["python", "-I", "-c", DIFF]},
                "final_diff",
                workspace_id,
                grant,
            )
        if result is None or result.status != "succeeded":
            raise RuntimeError("final diff capture failed")
        ref = result.stdout_ref or result.output_ref
        existing = self.store.db.execute(
            "SELECT record_ref FROM artifacts WHERE run_id=? AND execution_id=?",
            (self.run_id, result.execution_id),
        ).fetchone()
        if existing:
            return self.store.blobs.json(existing[0])["blob_ref"]
        artifact = ArtifactRecord(
            artifact_id=new_id("artifact"),
            run_id=self.run_id,
            execution_id=result.execution_id,
            blob_ref=ref,
            content_hash=digest(self.store.blobs.read(ref)),
            mime="text/x-diff",
            size=len(self.store.blobs.read(ref)),
            workspace_origin="outputs/final.diff",
        )
        self.last = self.store.register_artifact(artifact, causes=(self.last.event_id,))
        return ref

    def checkpoint(self):
        checkpoint = Checkpoint(
            checkpoint_id=new_id("cp"),
            run_id=self.run_id,
            completed_event_seq=self.last.run_seq,
            conversation_refs=tuple(self.store.blobs.put_json(group) for group in self.groups),
            model_turns=self.turns,
            attempted_calls=self.attempted,
            pending_ids=(),
            workspace_id=self.workspace_id,
            workspace_version=self.attempted,
        )
        self.last = self.store.checkpoint(checkpoint, causes=(self.last.event_id,))

    async def _run(self, source, task, *, verify_fixture=False, probe=False, resume_run_id=None):
        snapshot_guard = AsyncExitStack()
        if resume_run_id:
            self.run_id = resume_run_id
        self.store.blobs.begin_budget(self.config.limits.max_evidence_bytes)
        try:
            with self.spans.boundary("agent.run"):
                if resume_run_id is None:
                    metadata = (
                        {"scripted": True}
                        if isinstance(self.provider, ScriptedProvider)
                        else await self.provider.metadata(self.config.model)
                    )
                    if not probe and self.config.instructions_version.startswith("coder-"):
                        from local_agent.observability.events import TERMINAL
                        from local_agent.workspace.git import GitWorktrees
                        from local_agent.workspace.options import check_directory

                        worktrees = GitWorktrees(self.workspaces)
                        previous = self.workspace_options.get("continue_workspace_id")
                        if previous:
                            record = worktrees.load(previous)
                            if not record:
                                raise ValueError("Unknown managed Git workspace")
                            if self.expected_attempt is not None and any(
                                record.get(key) != self.expected_attempt.get(key)
                                for key in ("workspace_id", "run_id", "candidate_commit", "repository")
                            ):
                                raise ValueError("Workspace changed while the continuation was queued; refresh before continuing")
                            if self.store.run(record["run_id"])["status"] not in TERMINAL:
                                raise ValueError(
                                    "Previous task is active; stop or finish it before continuing"
                                )
                            pending = self.store.db.execute(
                                "SELECT 1 FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
                                "JOIN model_requests m ON m.id=t.request_id "
                                "WHERE m.run_id=? AND e.state NOT IN ('finished','reconciled')",
                                (record["run_id"],),
                            ).fetchone()
                            if pending:
                                raise ValueError(
                                    "Previous task has unresolved executions; reconcile it first"
                                )
                            if Path(record["repository"]).resolve() != source.resolve(strict=True):
                                raise ValueError(
                                    "Workspace belongs to a different source repository"
                                )
                            worktrees.verify(record)
                            from local_agent.environments.service import selected

                            inherited = selected(self.store, record["run_id"])
                            if inherited.get("prepared_environment"):
                                if (self.config.execution.container_pids_limit != 128
                                        and inherited.get("worker_hash") != self.sandbox.get("worker_hash")):
                                    raise ValueError(
                                        "Selected prepared image uses an older sandbox worker. "
                                        "Continue with container_pids_limit: 128, or start a new task "
                                        "from this workspace's commit and prepare its environment with the current worker."
                                    )
                                self.sandbox = self.base_sandbox = inherited
                                self.executor = DockerExecutor(self.store, self.workspaces,
                                    inherited["image"], settings=self.config.execution)
                                self.executor.fault_hook = self.fault
                                self.environment_inventory = inherited["prepared_environment"].get("inventory")
                            if self.expected_workspace is not None:
                                from local_agent.mobile.repair_controls import (
                                    validate_repair_target,
                                )

                                if previous != self.expected_workspace["workspace_id"]:
                                    raise ValueError("Repair workspace changed")
                                validate_repair_target(self.store.root, self.expected_workspace, source)
                            # Quiesce any retained keeper before capturing the next task's state.
                            container_record = (
                                self.store.control / "containers" / (previous + ".json")
                            )
                            if container_record.exists() and self.config.execution.execution_mode_default == "ephemeral":
                                from local_agent.executor.maintenance import sweep

                                await sweep(
                                    self.store.root,
                                    self.sandbox["image"],
                                    self.config.execution,
                                    workspace_id=previous,
                                )
                            else:
                                await snapshot_guard.enter_async_context(self.frozen_workspace(previous))
                            self.working_directory = self.workspace_options.get(
                                "working_directory", record.get("working_directory", ".")
                            )
                            check_directory(Path(record["worktree"]), self.working_directory)
                            worktrees.continue_task(
                                previous,
                                source,
                                self.run_id,
                                working_directory=self.working_directory,
                            )
                            self.workspace_id, self.path = previous, self.workspaces.path(previous)
                        else:
                            self.workspace_id, self.path = self.workspaces.create_coding(
                                source,
                                self.run_id,
                                base_ref=self.workspace_options.get("base_ref", "HEAD"),
                            )
                            check_directory(self.path / "project", self.working_directory)
                            record = worktrees.load(self.workspace_id)
                            if record:
                                record["working_directory"] = self.working_directory
                                worktrees.save(record)
                    else:
                        if self.workspace_options:
                            raise ValueError("Workspace task options require a coding profile")
                        self.workspace_id, self.path = self.workspaces.create(source)
                    self.baseline = self.store.control / "baselines" / self.run_id
                    private_directory(self.baseline.parent)
                    if self.workspaces.git_info(self.workspace_id):
                        from local_agent.workspace.git import GitWorktrees

                        GitWorktrees(self.workspaces).baseline(self.workspace_id, self.baseline)
                    else:
                        copy_tree(self.path / "project", self.baseline, exclude=IMPORT_EXCLUDES)
                    if (
                        self.config.project_tests
                        and not probe
                        and not verify_fixture
                        and self.config.instructions_version.startswith("coder-")
                    ):
                        from local_agent.testing.environment import prepare_environment
                        from local_agent.testing.plans import resolve

                        self.test_plan = resolve(self.path / "project", self.working_directory)
                        try:
                            self.sandbox = await prepare_environment(
                                self.store.root,
                                self.path / "project",
                                self.test_plan,
                                self.base_sandbox,
                            )
                            self.executor = DockerExecutor(
                                self.store,
                                self.workspaces,
                                self.sandbox["image"],
                                settings=self.config.execution,
                            )
                        except (RuntimeError, ValueError, OSError) as exc:
                            self.project_test_report = {
                                "status": "environment_blocked",
                                "error": str(exc),
                                "commands": [],
                                "plan": self.test_plan,
                            }
                    config_ref = self.store.blobs.put_json(
                        {
                            "agent": self.config.model_dump(mode="json"),
                            "instructions": self.instructions,
                            "task": task,
                            "policy": OFFLINE_POLICY,
                            "policy_hash": OFFLINE_HASH,
                            "sandbox": self.sandbox,
                            "model_metadata": metadata,
                            "capability_report": self.capability_report,
                            "verify_fixture": verify_fixture,
                            "probe": probe,
                            "git_workspace": self.workspaces.git_info(self.workspace_id),
                            "workspace_options": self.workspace_options,
                            "expected_workspace": self.expected_workspace,
                            "expected_attempt": self.expected_attempt,
                            "working_directory": self.working_directory,
                            "project_test_plan": self.test_plan,
                            "base_sandbox": self.base_sandbox,
                            "baseline_id": self.run_id,
                        }
                    )
                    self.last = self.store.create_run(
                        RunManifest(
                            run_id=self.run_id,
                            thread_id=new_id("thread"),
                            workspace_id=self.workspace_id,
                            source_revision=(self.workspaces.git_info(self.workspace_id) or {}).get(
                                "base_commit"
                            ),
                            config_ref=config_ref,
                            config_hash=digest(self.store.blobs.read(config_ref)),
                            model_identity=metadata.get("installed", {}).get(
                                "digest", "scripted-integration"
                            ),
                            sandbox_image_digest=self.sandbox["image"],
                            mode="live",
                            package_versions={"local-agent": "0.1.0"},
                        )
                    )
                    self.created = True
                    self.last = self.store.transition(
                        self.run_id, "running", causes=(self.last.event_id,)
                    )
                    self.event(
                        "model.selected",
                        "runtime",
                        {
                            "model": self.config.model,
                            "metadata_ref": self.store.blobs.put_json(metadata),
                            "rule": "configured_exact_installed_tag",
                            "capability_ref": self.store.blobs.put_json(self.capability_report)
                            if self.capability_report
                            else None,
                        },
                    )
                    if (
                        self.project_test_report
                        and self.project_test_report["status"] == "environment_blocked"
                    ):
                        self.event(
                            "project.tests",
                            "controller",
                            {"report_ref": self.store.blobs.put_json(self.project_test_report)},
                        )
                        if "prepare_environment" not in self.config.tools:
                            raise RuntimeError(
                                "Test environment blocked: " + self.project_test_report["error"]
                            )
                    _, bootstrap = await self.trusted(
                        "run_command", {"argv": ["python", "-I", "-c", BOOTSTRAP]}, "bootstrap"
                    )
                    if bootstrap is None or bootstrap.status != "succeeded":
                        raise RuntimeError("sandbox baseline initialization failed")
                    await snapshot_guard.aclose()
                else:
                    from local_agent.runtime.recovery import restore

                    restored = await restore(self, resume_run_id)
                    task = restored["task"]
                    verify_fixture = restored["verify_fixture"]
                    self.instructions = restored["instructions"]
                from local_agent.environments.browser_support import stage as stage_browser_runner

                stage_browser_runner(self)
                node_roots = self.sandbox.get("prepared_environment", {}).get("node_roots")
                if node_roots and resume_run_id is None:
                    from local_agent.environments.service import HYDRATE

                    _, hydrated = await self.trusted("run_command", {
                        "argv": ["python", "-I", "-c", HYDRATE, json.dumps(node_roots)],
                    }, "environment_hydrate")
                    if hydrated is None or hydrated.status != "succeeded":
                        raise RuntimeError("Prepared npm dependencies could not be copied into the workspace")
                if "environment_inventory" in self.config.tools:
                    await self.trusted("environment_inventory", {}, "environment_inventory")
                self.verifier = verify_fixture if isinstance(verify_fixture, str) else "calculator"
                if resume_run_id is None:
                    await self.prepare()
                if self.test_plan is not None:
                    from local_agent.testing.runner import RUNNER

                    helper = (
                        "import sys\n"
                        + "sys.argv=['test_project',"
                        + repr(json.dumps(self.test_plan))
                        + "]\n"
                        + RUNNER
                    )
                    (self.path / "tools/test_project.py").write_text(helper)
                fixed = self.fixed_messages(task)
                while True:
                    if self.restored_completion is not None:
                        answer = self.restored_completion
                        self.restored_completion = None
                        async with self.frozen_workspace():
                            completed = await self.complete(answer, verify_fixture)
                        if completed is not None:
                            return completed
                    await self.before_model()
                    self.check(model=True)
                    with self.spans.boundary("context.build"):
                        # An environment tool can update the image/inventory during a run.
                        fixed = self.fixed_messages(task)
                        snapshot, ref = self.context.build(fixed, self.groups)
                        if snapshot.exclusions:
                            self.event(
                                "context.compacted",
                                "context",
                                {
                                    "snapshot_ref": ref,
                                    "rule": "complete-exchanges-v1",
                                    "inputs": [item["source_ref"] for item in snapshot.exclusions],
                                    "summary_ref": self.context.summary_ref,
                                    "preserved_constraints_ref": self.store.blobs.put_json(fixed),
                                },
                            )
                        self.event("context.built", "context", {"snapshot_ref": ref})
                    with self.spans.boundary("model.generate"):
                        self.check_paid_budget(snapshot)
                        request = self.request(ref)
                        self.turns += 1
                        try:
                            model_task = asyncio.create_task(self.provider.generate(request))
                            model_deadline = time.monotonic() + min(
                                self.config.limits.model_timeout_seconds,
                                max(0, self.deadline - time.monotonic()),
                            )
                            try:
                                while not model_task.done():
                                    self.check()
                                    if time.monotonic() >= model_deadline:
                                        raise TimeoutError("model request timeout")
                                    await asyncio.wait([model_task], timeout=0.25)
                                returned = model_task.result()
                            finally:
                                if not model_task.done():
                                    model_task.cancel()
                                    await asyncio.gather(model_task, return_exceptions=True)
                        except Exception as exc:
                            self.event(
                                "model.failed",
                                "model",
                                {
                                    "request_id": request.request_id,
                                    "type": type(exc).__name__,
                                    "detail": str(exc),
                                    "response_ref": getattr(exc, "raw_ref", None),
                                },
                            )
                            prior_repair = any(
                                e.event_type == "retry.decided" and e.data.get("rule") == "local-tool-response-repair-v1"
                                for e in self.store.events(self.run_id)
                            )
                            if (self.config.provider == "ollama" and self.config.tools
                                    and getattr(exc, "recoverable_tool_error", False)
                                    and not prior_repair):
                                self.event("retry.decided", "runtime", {
                                    "prior_request_id": request.request_id,
                                    "selected_action": "one_corrected_local_response",
                                    "rule": "local-tool-response-repair-v1"})
                                self.groups.append([{"role": "user", "content":
                                    "Controller feedback: the preceding model response could not be parsed or exceeded its output limit. No tool calls from it were dispatched. "
                                    "Produce exactly one small tool call with complete valid JSON. Do not repeat a large batch or rewrite whole files; prefer a small exact patch. "
                                    "The same model-turn/time limits still apply. Error: " + str(exc)[:1200]}])
                                self.checkpoint()
                                continue
                            raise
                        response, calls, proposals = self.response(request, returned)
                        used = (response.usage or {}).get("prompt_eval_count")
                        if used is not None and used > (
                            self.config.window_tokens - self.config.output_reserve_tokens
                        ):
                            self.event(
                                "budget.exhausted",
                                "context",
                                {
                                    "reason": "provider input count exceeded reserved input budget",
                                    "actual_input_tokens": used,
                                    "snapshot_ref": ref,
                                },
                            )
                            raise BudgetExhausted("provider input context exceeded budget")
                    raw = self.store.blobs.json(response.original_response_ref)
                    assistant = assistant_message(raw, response)
                    group = [assistant]
                    image_execution_ids = []
                    for index, (call, proposal) in enumerate(zip(calls, proposals, strict=True)):
                        try:
                            preview, result = await self.dispatch(call, proposal)
                        except BudgetExhausted:
                            state = self.store.db.execute(
                                "SELECT validated_ref,rejected FROM tool_calls WHERE id=?",
                                (call.call_id,),
                            ).fetchone()
                            skipped_index = index + int(
                                bool(state["validated_ref"] or state["rejected"])
                            )
                            self.event(
                                "budget.exhausted",
                                "runtime",
                                {"skipped_call_ids": [c.call_id for c in calls[skipped_index:]]},
                            )
                            raise
                        group.append(tool_message(call, preview))
                        if (
                            result is not None
                            and result.status == "succeeded"
                            and call.name in {"render_pdf_region", "view_image"}
                        ):
                            image_execution_ids.append(result.execution_id)
                    group.extend(
                        image_messages(
                            self.store, self.run_id, image_execution_ids, self.config.provider
                        )
                    )
                    self.groups.append(group)
                    self.checkpoint()
                    if calls:
                        continue
                    self.completion_response_id = response.request_id
                    async with self.frozen_workspace():
                        completed = await self.complete(response.text, verify_fixture)
                    if completed is not None:
                        return completed
        except (AuditUnavailable, OSError) as exc:
            self.store.healthy = False
            await self.executor.emergency_cleanup(self.run_id)
            return {"run_id": self.run_id, "status": "audit_unavailable", "error": str(exc)}
        except Exception as exc:
            from local_agent.runtime.recovery import NeedsReconciliation
            from local_agent.runtime.repair_progress import LocalStalled

            status = (
                "local_stalled" if isinstance(exc, LocalStalled) else
                "budget_exhausted"
                if isinstance(exc, BudgetExhausted)
                else (
                    "cancelled"
                    if isinstance(exc, RunCancelled)
                    else (
                        "needs_reconciliation" if isinstance(exc, NeedsReconciliation) else "failed"
                    )
                )
            )
            if self.created and self.store.healthy:
                await self.executor.emergency_cleanup(self.run_id)
                with self.spans.boundary("agent.run"):
                    pending = self.store.db.execute(
                        "SELECT 1 FROM execution_attempts e JOIN tool_calls t ON t.id=e.call_id "
                        "JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=? AND e.state!='finished'",
                        (self.run_id,),
                    ).fetchone()
                    if pending:
                        status = "needs_reconciliation"
                    skipped = [
                        row[0]
                        for row in self.store.db.execute(
                            "SELECT t.id FROM tool_calls t JOIN model_requests m ON m.id=t.request_id "
                            "WHERE m.run_id=? AND t.validated_ref IS NULL AND t.rejected=0",
                            (self.run_id,),
                        )
                    ]
                    marked = {
                        call_id
                        for event in self.store.events(self.run_id)
                        for call_id in event.data.get("skipped_call_ids", [])
                    }
                    skipped = [call_id for call_id in skipped if call_id not in marked]
                    if skipped:
                        self.event(
                            "tool.skipped",
                            "runtime",
                            {
                                "skipped_call_ids": skipped,
                                "terminal_reason": status,
                                "reason": type(exc).__name__,
                            },
                        )
                    self.last = self.store.transition(
                        self.run_id,
                        status,
                        causes=(self.last.event_id,),
                        reason={"type": type(exc).__name__, "detail": str(exc)},
                    )
            return {
                "run_id": self.run_id,
                "status": status,
                "error": str(exc),
                **({"repair_progress": self.repair_guard.public()}
                   if getattr(self, "repair_guard", None) else {}),
                **(
                    {"project_tests": self.project_test_report}
                    if self.project_test_report is not None
                    else {}
                ),
            }
        finally:
            await snapshot_guard.aclose()
            self.store.blobs.end_budget()
            if hasattr(self.provider, "close"):
                await self.provider.close()
            self.spans.shutdown()
