import asyncio
import json
import threading
from pathlib import Path

import httpx
import pytest

from local_agent.config import INSTRUCTIONS, load_config
from local_agent.contracts import AgentConfig, ModelRequest, new_id
from local_agent.models.openai import OpenAIProvider
from local_agent.observability.audit import audit
from local_agent.observability.browser import TraceServer
from local_agent.runtime.context import ContextBuilder
from local_agent.runtime.loop import simulate
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store


def config(**updates):
    return AgentConfig(
        instructions_hash=digest(INSTRUCTIONS.encode()),
        provider="openai",
        model="test-model",
        **updates,
    )


def request(store, cfg, groups=()):
    snapshot, ref = ContextBuilder(store.blobs, cfg).build(
        [{"role": "system", "content": "Constraints"}, {"role": "user", "content": "Task"}], groups
    )
    return snapshot, ModelRequest(
        request_id=new_id("req"),
        run_id=new_id("run"),
        context_ref=ref,
        provider="openai",
        model=cfg.model,
        options={},
        deadline_utc="2099-01-01T00:00:00Z",
        trace_id="1" * 32,
        parent_span_id="2" * 16,
    )


def response(arguments='{"path":"project/a"}'):
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "provider-call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": arguments},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 123, "completion_tokens": 30},
    }


def test_openai_exact_wire_tool_id_usage_and_secret_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-token")
    store = Store(tmp_path / "data")
    cfg = config()
    snapshot, req = request(store, cfg)
    expected = store.blobs.read(snapshot.payload_ref)
    raw = response()

    def server(incoming):
        assert incoming.url.path == "/v1/chat/completions"
        assert incoming.content == expected
        assert incoming.headers["Authorization"] == "Bearer test-secret-token"
        assert "options" not in json.loads(incoming.content)
        assert "test-secret-token" not in incoming.content.decode()
        return httpx.Response(200, json=raw)

    provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(server))
    result = asyncio.run(provider.generate(req))
    assert result.tool_calls[0].provider_id == "provider-call-1"
    assert result.tool_calls[0].arguments == {"path": "project/a"}
    assert result.usage["prompt_eval_count"] == 123
    assert "eval_duration" not in result.usage
    assert store.blobs.json(result.original_response_ref) == raw
    groups = [
        [
            raw["choices"][0]["message"],
            {
                "role": "tool",
                "tool_name": "read_file",
                "tool_call_id": "provider-call-1",
                "content": "result",
            },
        ]
    ]
    snapshot, _ = request(store, cfg, groups)
    wire = store.blobs.json(snapshot.payload_ref)
    assert wire["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "provider-call-1",
        "content": "result",
    }
    assert "test-secret-token" not in str(cfg.model_dump())
    asyncio.run(provider.close())
    store.close()


@pytest.mark.parametrize(
    "body,status",
    [
        (b"not json", 200),
        (b'{"error":"oops"}', 429),
        (
            json.dumps(
                {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}
            ).encode(),
            200,
        ),
    ],
)
def test_openai_failures_preserve_raw_bytes(tmp_path, body, status):
    from local_agent.models.ollama import ProviderResponseError

    store = Store(tmp_path / "data")
    cfg = config(base_url="http://127.0.0.1:1234/v1", api_key_env=None)
    _, req = request(store, cfg)
    provider = OpenAIProvider(
        store.blobs,
        cfg,
        transport=httpx.MockTransport(lambda incoming: httpx.Response(status, content=body)),
    )
    with pytest.raises(ProviderResponseError) as error:
        asyncio.run(provider.generate(req))
    assert store.blobs.read(error.value.raw_ref) == body
    asyncio.run(provider.close())
    store.close()


def test_malformed_arguments_are_validation_proposals(tmp_path):
    store = Store(tmp_path / "data")
    cfg = config(base_url="http://localhost:1234/v1", api_key_env=None)
    _, req = request(store, cfg)
    provider = OpenAIProvider(
        store.blobs,
        cfg,
        transport=httpx.MockTransport(lambda incoming: httpx.Response(200, json=response("{bad"))),
    )
    result = asyncio.run(provider.generate(req))
    assert result.tool_calls[0].arguments == "{bad"
    asyncio.run(provider.close())
    store.close()


def test_endpoint_and_key_validation(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = Store(tmp_path / "data")
    with pytest.raises(ValueError, match="environment"):
        OpenAIProvider(store.blobs, config())
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAIProvider(store.blobs, config(base_url="http://example.com/v1"))
    with pytest.raises(ValueError, match="credentials"):
        OpenAIProvider(store.blobs, config(base_url="https://user:pass@example.com/v1"))
    store.close()


def test_readonly_browser_routes_isolation_and_host_checks(tmp_path):
    store = Store(tmp_path / "data")
    run_id = asyncio.run(simulate(store))["run_id"]
    foreign = store.blobs.put(b"not part of this run")
    db_before = store.db.total_changes
    server = TraceServer(store.root, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with httpx.Client(trust_env=False) as client:
            page = client.get(url)
            assert page.status_code == 200
            assert "textContent" in page.text and "innerHTML" not in page.text
            assert "frame-ancestors" in page.headers["Content-Security-Policy"]
            assert client.get(url + "/api/runs").json()[0]["id"] == run_id
            data = client.get(url + "/api/runs/" + run_id).json()
            assert data["events"]
            assert client.get(url + "/api/runs/" + run_id + "/audit").json()["ok"]
            ref = store.run(run_id)["manifest_ref"]
            assert client.get(url + f"/api/runs/{run_id}/evidence/{ref[7:]}").status_code == 200
            assert client.get(url + f"/api/runs/{run_id}/evidence/{foreign[7:]}").status_code == 403
            assert client.get(url, headers={"Host": "evil.example"}).status_code == 403
            assert client.get(url, headers={"Origin": "https://evil.example"}).status_code == 403
            assert client.post(url + "/api/runs/" + run_id).status_code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert store.db.total_changes == db_before
    assert audit(store, run_id)["ok"]
    store.close()


def test_openai_factory_runtime_and_audit_with_real_docker(tmp_path, request):
    from local_agent.doctor import sandbox_config
    from local_agent.runtime.agent import Agent

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store = Store(tmp_path / "data")
    cfg = load_config(Path("config/openai-local.yaml"))
    calls = []

    def server(incoming):
        if incoming.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": cfg.model, "created": 1}]})
        wire = json.loads(incoming.content)
        calls.append(wire)
        if len(calls) == 1:
            return httpx.Response(200, json=response())
        assert wire["messages"][-1]["tool_call_id"] == "provider-call-1"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": "Done"}}
                ]
            },
        )

    source = tmp_path / "repo"
    source.mkdir()
    (source / "a").write_text("hello")
    provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(server))
    result = asyncio.run(
        Agent(store, cfg, {**sandbox_config(), "image": image}, provider=provider).run(
            source, "Read a"
        )
    )
    assert result["status"] == "completed_unverified", result
    checked = audit(store, result["run_id"])
    assert checked["ok"], checked["errors"]
    store.close()


def test_openai_resume_preserves_provider_tool_id_without_redispatch(tmp_path, request):
    from local_agent.doctor import sandbox_config
    from local_agent.runtime.agent import Agent

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store = Store(tmp_path / "data")
    cfg = load_config(Path("config/openai-local.yaml"))
    wires = []

    def server(incoming):
        if incoming.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": cfg.model, "created": 1}]})
        wire = json.loads(incoming.content)
        wires.append(wire)
        if len(wires) == 1:
            return httpx.Response(200, json=response())
        assert wire["messages"][-1]["tool_call_id"] == "provider-call-1"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Resumed"},
                    }
                ]
            },
        )

    class ControllerExit(BaseException):
        pass

    def crash(point):
        if point == "after_result_commit":
            raise ControllerExit()

    source = tmp_path / "repo"
    source.mkdir()
    (source / "a").write_text("hello")
    sandbox = {**sandbox_config(), "image": image}
    provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(server))
    first = Agent(store, cfg, sandbox, provider=provider, fault_hook=crash)
    with pytest.raises(ControllerExit):
        asyncio.run(first.run(source, "Read a"))
    assert store.run(first.run_id)["status"] == "running"
    replacement = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(server))
    result = asyncio.run(
        Agent(store, cfg, sandbox, provider=replacement).run(None, "", resume_run_id=first.run_id)
    )
    assert result["status"] == "completed_unverified", result
    executions = store.db.execute(
        "SELECT e.request_ref FROM execution_attempts e JOIN tool_calls t "
        "ON t.id=e.call_id JOIN model_requests m ON m.id=t.request_id WHERE m.run_id=?",
        (first.run_id,),
    ).fetchall()
    assert sum(store.blobs.json(row[0])["tool"] == "read_file" for row in executions) == 1
    assert audit(store, first.run_id)["ok"]
    store.close()


def test_cancellation_after_response_records_skipped_calls(tmp_path, request):
    from local_agent.doctor import sandbox_config
    from local_agent.models.scripted import ScriptedProvider
    from local_agent.runtime.agent import Agent

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    store = Store(tmp_path / "data")
    source = tmp_path / "repo"
    source.mkdir()
    provider = ScriptedProvider(
        responses=(
            {
                "text": "",
                "tool_calls": [
                    {"name": "run_command", "arguments": {"argv": ["python", "-c", "print(123)"]}}
                ],
                "finish_status": "tool_calls",
            },
        )
    )
    agent = Agent(
        store,
        load_config(Path("config/coder.yaml")),
        {**sandbox_config(), "image": image},
        provider=provider,
    )

    def cancel_after_response(point):
        if point == "after_response_persistence":
            agent.event("cancel.requested", "user", {"reason": "test boundary"})

    agent.fault_hook = cancel_after_response
    result = asyncio.run(agent.run(source, "Wait"))
    assert result["status"] == "cancelled"
    assert any(
        e.event_type == "tool.skipped" and e.data["skipped_call_ids"]
        for e in store.events(result["run_id"])
    )
    checked = audit(store, result["run_id"])
    assert checked["ok"], checked["errors"]
    store.close()


def test_openai_credit_error_is_actionable_without_echoing_provider_secrets(tmp_path):
    from local_agent.models.ollama import ProviderResponseError

    store = Store(tmp_path / "data")
    cfg = config(base_url="http://localhost:1234/v1", api_key_env=None)
    _, req = request(store, cfg)
    body = {
        "error": {
            "type": "insufficient_quota",
            "code": "credit_balance_exhausted",
            "message": "fake-private-content",
        }
    }
    provider = OpenAIProvider(
        store.blobs, cfg, transport=httpx.MockTransport(lambda _: httpx.Response(429, json=body))
    )
    try:
        with pytest.raises(ProviderResponseError, match="credit balance/quota exhausted") as error:
            asyncio.run(provider.generate(req))
        assert "fake-private-content" not in str(error.value)
        assert store.blobs.json(error.value.raw_ref) == body
    finally:
        asyncio.run(provider.close())
        store.close()
