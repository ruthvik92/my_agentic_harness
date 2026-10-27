"""Controller acceptance checks for the harness-authored screenshot runtime."""

import asyncio
import base64
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from local_agent.config import load_config
from local_agent.mobile import ScreenshotAgent, validate_request
from local_agent.models.scripted import ScriptedProvider
from local_agent.observability.audit import audit
from local_agent.runtime.context import ContextBuilder
from local_agent.storage.blobs import BlobStore
from local_agent.storage.bundles import roots
from local_agent.storage.database import Store


def screenshot(format="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format=format)
    return stream.getvalue()


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"question": " "},
        {"question": True},
        {"question": "x" * 8001},
        {"question": "hi", "command": "anything"},
        {"question": "hi", "image": None},
        {"question": "hi", "image": "not base64"},
        {"question": "hi", "image": base64.b64encode(b"not an image").decode()},
        {"question": "hi", "history": "wrong"},
        {"question": "hi", "history": [None]},
        {"question": "hi", "history": [{"role": "system", "content": "hi"}]},
        {"question": "hi", "history": [{"role": "user", "content": 1}]},
        {"question": "hi", "history": [{"role": "user", "content": "x" * 16001}]},
        {"question": "hi", "history": [{"role": "user", "content": "x", "extra": 1}]},
        {"question": "hi", "image": base64.b64encode(screenshot("GIF")).decode()},
    ],
)
def test_invalid_requests_are_rejected(value):
    with pytest.raises(ValueError):
        validate_request(value)


@pytest.mark.parametrize(
    "provider,format,mime", [("ollama", "PNG", "image/png"), ("openai", "JPEG", "image/jpeg")]
)
def test_followup_image_formats_and_context_without_tools(tmp_path, provider, format, mime):
    blobs = BlobStore(tmp_path / "blobs")
    raw = screenshot(format)
    history = [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    validate_request(
        {"question": "And now?", "image": base64.b64encode(raw).decode(), "history": history}
    )
    prepared_ref = blobs.put_json(
        {"image_ref": blobs.put(raw), "mime": mime, "history_ref": blobs.put_json(history)}
    )
    cfg = load_config(Path("tests/fixtures/configs/phone.yaml")).model_copy(update={"provider": provider})
    agent = object.__new__(ScreenshotAgent)
    agent.store = SimpleNamespace(
        blobs=blobs,
        events=lambda _: [
            SimpleNamespace(event_type="screenshot.prepared", data={"input_ref": prepared_ref})
        ],
    )
    agent.config, agent.instructions, agent.run_id = cfg, "Instructions", "unused"
    messages = agent.fixed_messages("And now?")
    assert messages[1]["role"] == "system"
    assert "4 MiB and 16 million pixels" in messages[1]["content"]
    assert "no filesystem or command tools" in messages[1]["content"]
    assert messages[2:4] == history
    if provider == "ollama":
        assert base64.b64decode(messages[-1]["images"][0]) == raw
    else:
        assert messages[-1]["content"][1]["image_url"]["url"].startswith(f"data:{mime};base64,")
    snapshot, _ = ContextBuilder(blobs, cfg).build(messages, [])
    assert "tools" not in blobs.json(snapshot.payload_ref)


@pytest.mark.parametrize("agent_config", [
    "tests/fixtures/configs/phone.yaml", "examples/configs/openai-reviewer.yaml",
])
def test_screenshot_uses_durable_runtime_and_audits(tmp_path, request, agent_config):
    from local_agent.doctor import sandbox_config

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    source = tmp_path / "source"
    source.mkdir()
    store = Store(tmp_path / "state")
    raw = screenshot()
    cfg = load_config(Path(agent_config))
    provider = ScriptedProvider(
        responses=({"text": "A test screenshot.", "tool_calls": [], "finish_status": "stop"},)
    )
    agent = ScreenshotAgent(
        store,
        cfg,
        {**sandbox_config(), "image": image},
        provider=provider,
        request={"question": "Explain", "image": base64.b64encode(raw).decode()},
    )
    result = asyncio.run(agent.run(source, "Explain"))
    try:
        assert result["status"] == "completed_unverified", result
        assert result["answer"] == "A test screenshot."
        evidence, _ = roots(store, result["run_id"])
        assert store.blobs.put(raw) in evidence
        checked = audit(store, result["run_id"])
        assert checked["ok"], checked["errors"]
        assert any(e.event_type == "screenshot.prepared" for e in store.events(result["run_id"]))
        assert agent.prepared()["image_info"] == {
            "width": 16,
            "height": 16,
            "bytes": len(raw),
            "mime": "image/png",
        }
    finally:
        store.close()


def test_review_capture_budget_failure_recovers_without_model_replay(
    tmp_path, request, monkeypatch
):
    from local_agent.doctor import sandbox_config
    from local_agent.mobile.jobs import publish
    from local_agent.mobile.recovery import recover_review
    from local_agent.mobile.threads import Threads

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root = tmp_path / "state"
    source = tmp_path / "source"
    source.mkdir()
    store = Store(root)
    cfg = load_config(Path("examples/configs/openai-reviewer.yaml"))
    cfg = cfg.model_copy(
        update={"limits": cfg.limits.model_copy(update={"max_attempted_tool_calls": 1})}
    )
    import httpx

    from local_agent.models.openai import OpenAIProvider

    monkeypatch.setenv("OPENAI_API_KEY", "test-no-network")

    def endpoint(incoming):
        if incoming.method == "GET":
            return httpx.Response(200, json={"data": [{"id": cfg.model}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Recorded critique"},
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3},
            },
        )

    provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(endpoint))
    agent = ScreenshotAgent(
        store,
        cfg,
        {**sandbox_config(), "image": image},
        provider=provider,
        request={"question": "Review"},
    )
    result = asyncio.run(agent.run(source, "Review"))
    try:
        assert result["status"] == "budget_exhausted"
        assert audit(store, result["run_id"])["ok"]
        threads = Threads(root)
        tid = threads.create("Recovery test")
        job = {
            "job_id": "a" * 32,
            "thread_id": tid,
            "run_id": result["run_id"],
            "status": "failed",
            "kind": "review",
            "error": "attempted tools",
            "question": "Review",
            "model": cfg.model,
        }
        (root / "phone/jobs" / job["job_id"]).mkdir(parents=True)
        publish(root / "phone/jobs" / job["job_id"] / "status.json", job)
        assert recover_review(root, job, threads)
        recovered = threads.get(tid)
        assert "Recorded critique" in recovered["messages"][-1]["content"]
        assert recovered["messages"][-1]["recovered"]
        assert store.run(result["run_id"])["status"] == "budget_exhausted"
        assert job["status"] == "failed"
        assert audit(store, job["recovered_review"]["activity_run_id"])["ok"]
        assert not recover_review(root, job, threads)
        assert len(threads.get(tid)["messages"]) == 2
    finally:
        store.close()
