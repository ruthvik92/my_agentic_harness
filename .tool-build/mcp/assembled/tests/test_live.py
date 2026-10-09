import asyncio
from pathlib import Path

import httpx
import pytest

from local_agent.config import INSTRUCTIONS, load_config
from local_agent.contracts import AgentConfig, ModelRequest, new_id
from local_agent.doctor import sandbox_config
from local_agent.models.ollama import OllamaProvider
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.agent import Agent
from local_agent.runtime.context import ContextBuilder, estimate
from local_agent.storage.blobs import digest
from local_agent.storage.database import Store

FIXTURE = Path(__file__).parent / "fixtures" / "broken_repo"


def test_native_adapter_preserves_payload_and_message(tmp_path):
    store = Store(tmp_path / "data")
    raw = {
        "done": True,
        "done_reason": "stop",
        "message": {
            "role": "assistant",
            "content": "",
            "thinking": "optional provider field",
            "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "project/a"}}}],
        },
        "prompt_eval_count": 20,
        "eval_count": 10,
        "eval_duration": 1000,
    }
    config = AgentConfig(instructions_hash=digest(INSTRUCTIONS.encode()), model="test")
    snapshot, ref = ContextBuilder(store.blobs, config).build(
        [{"role": "user", "content": "test"}], []
    )
    expected = store.blobs.read(snapshot.payload_ref)

    def server(request):
        assert request.content == expected
        assert "authorization" not in request.headers
        return httpx.Response(200, json=raw)

    provider = OllamaProvider(store.blobs, transport=httpx.MockTransport(server))
    request = ModelRequest(
        request_id=new_id("req"),
        run_id=new_id("run"),
        context_ref=ref,
        provider="ollama",
        model="test",
        options={},
        deadline_utc="2099-01-01T00:00:00Z",
        trace_id="1" * 32,
        parent_span_id="2" * 16,
    )
    result = asyncio.run(provider.generate(request))
    assert result.tool_calls[0].name == "read_file"
    assert result.usage["load_duration"] is None
    assert store.blobs.json(result.original_response_ref) == raw
    asyncio.run(provider.close())
    store.close()


def test_context_preserves_complete_groups_and_constraints(tmp_path):
    store = Store(tmp_path / "data")
    config = AgentConfig(
        instructions_hash=digest(b"fixed"), window_tokens=4096, output_reserve_tokens=2048
    )
    group = [
        {
            "role": "assistant",
            "content": "x" * 3000,
            "tool_calls": [{"function": {"name": "read_file"}}],
        },
        {"role": "tool", "tool_name": "read_file", "content": "y" * 3000},
    ]
    fixed = [{"role": "system", "content": "preserved constraint"}]
    snapshot, _ = ContextBuilder(store.blobs, config).build(fixed, [group])
    assert snapshot.messages[: len(fixed)] == tuple(fixed)
    assert snapshot.exclusions
    assert estimate(store.blobs.json(snapshot.payload_ref)) <= 2048
    store.close()


def test_live_scripted_repair_has_real_independent_verification(tmp_path, request):
    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    sandbox = {**sandbox_config(), "image": image}
    original = digest((FIXTURE / "calculator.py").read_bytes())
    provider = ScriptedProvider(
        responses=(
            {
                "text": "Inspect and reproduce",
                "tool_calls": [
                    {"name": "read_file", "arguments": {"path": "project/calculator.py"}},
                    {
                        "name": "run_command",
                        "arguments": {"argv": ["python", "-m", "pytest", "-q"]},
                    },
                ],
                "finish_status": "tool_calls",
            },
            {
                "text": "Repair",
                "tool_calls": [
                    {
                        "name": "patch_file",
                        "arguments": {
                            "path": "project/calculator.py",
                            "old_text": "a - b",
                            "new_text": "a + b",
                            "expected_hash": original,
                        },
                    },
                    {
                        "name": "run_command",
                        "arguments": {"argv": ["python", "-m", "pytest", "-q"]},
                    },
                ],
                "finish_status": "tool_calls",
            },
            {"text": "Fixed", "tool_calls": [], "finish_status": "stop"},
        )
    )
    config = load_config(Path("config/coder.yaml"))
    store = Store(tmp_path / "data")
    result = asyncio.run(
        Agent(store, config, sandbox, provider=provider).run(
            FIXTURE, "Fix add", verify_fixture=True
        )
    )
    assert result["status"] == "verified", result
    report = audit(store, result["run_id"])
    assert report["ok"], report["errors"]
    assert b"+    return a + b" in store.blobs.read(result["diff_ref"])
    assert "a - b" in (FIXTURE / "calculator.py").read_text()
    event = next(e for e in store.events(result["run_id"]) if e.event_type == "completion.verified")
    assert (
        event.data["workspace_id"]
        != store.blobs.json(store.run(result["run_id"])["manifest_ref"])["workspace_id"]
    )
    store.close()


@pytest.mark.parametrize(
    "body,status",
    [
        (b'{"done":true}', 200),
        (b"not JSON", 200),
        (
            b'{"done":true,"done_reason":"length","eval_count":8192,"message":'
            b'{"role":"assistant","content":"partial","tool_calls":[{"function":'
            b'{"name":"read_file","arguments":{"path":"project/a"}}}]} }',
            200,
        ),
        (b'{"error":"unavailable"}', 503),
    ],
)
def test_failed_provider_responses_keep_raw_evidence(tmp_path, body, status):
    from local_agent.models.ollama import ProviderResponseError

    store = Store(tmp_path / "data")
    config = AgentConfig(instructions_hash=digest(b"fixed"), model="test")
    _, ref = ContextBuilder(store.blobs, config).build([{"role": "user", "content": "test"}], [])
    provider = OllamaProvider(
        store.blobs,
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body)),
    )
    request = ModelRequest(
        request_id=new_id("req"),
        run_id=new_id("run"),
        context_ref=ref,
        provider="ollama",
        model="test",
        options={},
        deadline_utc="2099-01-01T00:00:00Z",
        trace_id="1" * 32,
        parent_span_id="2" * 16,
    )
    with pytest.raises(ProviderResponseError) as error:
        asyncio.run(provider.generate(request))
    assert store.blobs.read(error.value.raw_ref) == body
    if b'"done_reason":"length"' in body:
        assert "output token limit reached (eval_count=8192)" in str(error.value)
    asyncio.run(provider.close())
    store.close()
