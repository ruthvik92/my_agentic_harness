from pathlib import Path

import pytest

from local_agent.contracts import (
    ContextSnapshot,
    ExecutionRequest,
    ModelRequest,
    ModelResponse,
    RunManifest,
    ToolCall,
    new_id,
)
from local_agent.executor.docker import DockerExecutor
from local_agent.observability.spans import Spans, correlation
from local_agent.policy.engine import OFFLINE_HASH, OFFLINE_POLICY, offline_evaluate
from local_agent.storage.blobs import canonical, digest
from local_agent.storage.database import Store
from local_agent.tools.registry import SCHEMAS, VERSIONS, normalize
from local_agent.workspace.manager import Workspaces


def pytest_addoption(parser):
    parser.addoption(
        "--docker-image", default=None, help="Immutable image ID to run Docker acceptance tests"
    )


class Sandbox:
    def __init__(self, root, source, image):
        self.store = Store(root)
        self.workspaces = Workspaces(root)
        self.workspace_id, self.path = self.workspaces.create(source)
        self.run_id = new_id("run")
        self.executor = DockerExecutor(self.store, self.workspaces, image)
        config_ref = self.store.blobs.put_json(
            {"policy": OFFLINE_POLICY, "policy_hash": OFFLINE_HASH}
        )
        self.store.create_run(
            RunManifest(
                run_id=self.run_id,
                thread_id=new_id("thread"),
                workspace_id=self.workspace_id,
                config_ref=config_ref,
                config_hash=digest(self.store.blobs.read(config_ref)),
                model_identity="scripted-integration",
                sandbox_image_digest=image,
                mode="live",
                package_versions={},
            )
        )
        self.store.transition(self.run_id, "running")

    async def execute(self, name, arguments):
        ctx = correlation()
        payload_ref = self.store.blobs.put_json({"messages": [], "tools": []})
        snapshot_ref = self.store.blobs.put_json(ContextSnapshot(
            messages=(), tool_definitions=(), payload_ref=payload_ref,
            payload_hash=digest(self.store.blobs.read(payload_ref)), provenance=(), token_estimate=0,
        ))
        request = ModelRequest(
            request_id=new_id("req"),
            run_id=self.run_id,
            context_ref=snapshot_ref,
            provider="scripted",
            model="test",
            options={},
            deadline_utc="2099-01-01T00:00:00Z",
            trace_id=ctx["trace_id"],
            parent_span_id=ctx["span_id"],
        )
        requested = self.store.record_request(request, causes=())
        raw = {
            "text": "",
            "tool_calls": [{"name": name, "arguments": arguments}],
            "finish_status": "tool_calls",
        }
        response = ModelResponse.model_validate_json(
            canonical(
                {
                    **raw,
                    "request_id": request.request_id,
                    "original_response_ref": self.store.blobs.put_json(raw),
                }
            )
        )
        call = ToolCall(
            call_id=new_id("call"),
            request_id=request.request_id,
            index=0,
            name=name,
            tool_version=VERSIONS[name],
            arguments_ref=self.store.blobs.put_json(arguments),
        )
        _, proposed = self.store.record_response(
            self.run_id, response, (call,), causes=(requested.event_id,)
        )
        normalized = normalize(name, arguments)
        validated = self.store.record_validation(
            self.run_id, call.call_id, normalized, None, causes=(proposed[0].event_id,)
        )
        decision = offline_evaluate(
            call.call_id, normalized, self.store.blobs.put_json(normalized), tuple(SCHEMAS)
        )
        authorized = self.store.record_policy(self.run_id, decision, causes=(validated.event_id,))
        execution = ExecutionRequest(
            execution_id=new_id("exec"),
            call_id=call.call_id,
            workspace_id=self.workspace_id,
            tool=name,
            tool_version=call.tool_version,
            arguments=normalized["arguments"],
            authorization_ref=decision.decision_id,
            normalized_request_hash=decision.normalized_request_hash,
            trace_id=ctx["trace_id"],
            parent_span_id=ctx["span_id"],
        )
        intent = self.store.commit_dispatch(self.run_id, execution, causes=(authorized.event_id,))
        started = self.store.execution_event(
            self.run_id, execution.execution_id, causes=(intent.event_id,)
        )
        result = await self.executor.execute(execution)
        self.store.execution_event(
            self.run_id, execution.execution_id, result, causes=(started.event_id,)
        )
        await self.executor.release(execution.execution_id)
        return result


@pytest.fixture
def sandbox(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("Docker acceptance requires --docker-image sha256:...")
    spans = Spans()
    with spans.boundary("agent.run"):
        value = Sandbox(
            tmp_path / "data", Path(__file__).parent / "fixtures" / "broken_repo", image
        )
        try:
            yield value
        finally:
            value.store.close()
    spans.shutdown()
