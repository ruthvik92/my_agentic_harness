"""Responses transport and audited workspace tool loop, without live inference."""

import asyncio
import json

import httpx
import pytest
from test_workspace_review import candidate, review_config  # noqa: F401

from local_agent.models.responses import input_items, normalize_response, uses_responses
from local_agent.runtime.context import ContextBuilder
from local_agent.storage.database import Store


def output(*, calls=False, arguments='{"path":"project/value.py"}'):
    items = [
        {"id": "rs_1", "type": "reasoning", "summary": [], "encrypted_content": "opaque-ciphertext"}
    ]
    if calls:
        items.extend(
            [
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_diff",
                    "name": "read_file",
                    "arguments": '{"path":"scratch/review.diff"}',
                    "status": "completed",
                },
                {
                    "id": "fc_2",
                    "type": "function_call",
                    "call_id": "call_file",
                    "name": "read_file",
                    "arguments": arguments,
                    "status": "completed",
                },
            ]
        )
    else:
        items.append(
            {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "phase": "final_answer",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "text": json.dumps(
                            {
                                "verdict": "approve",
                                "summary": "Read code/diff and checked execution evidence.",
                            }
                        ),
                    }
                ],
            }
        )
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "output": items,
        "usage": {
            "input_tokens": 123,
            "output_tokens": 42,
            "input_tokens_details": {"cached_tokens": 7},
            "output_tokens_details": {"reasoning_tokens": 12},
        },
    }


def test_responses_workspace_transport_tools_reasoning_usage_and_audit(
    candidate, monkeypatch, request  # noqa: F811
):
    from local_agent.doctor import sandbox_config
    from local_agent.mobile.tokens import job_usage
    from local_agent.mobile.workspace_review import run_review
    from local_agent.models.openai import OpenAIProvider

    image = request.config.getoption("--docker-image")
    if image is None:
        pytest.skip("requires --docker-image")
    root, repository, project, target = candidate
    cfg = review_config(monkeypatch).model_copy(update={"model": "gpt-6.1-sol"})
    monkeypatch.setenv("OPENAI_API_KEY", "fake-responses-key")
    store = Store(root)
    wires = []

    def endpoint(incoming):
        if incoming.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": cfg.model}]})
        assert incoming.url.path == "/v1/responses"
        assert incoming.headers["Authorization"] == "Bearer fake-responses-key"
        assert b"fake-responses-key" not in incoming.content
        wire = json.loads(incoming.content)
        wires.append(wire)
        assert wire["reasoning"] == {"effort": "medium"}
        assert "reasoning_effort" not in wire and "messages" not in wire
        assert wire["max_output_tokens"] == cfg.output_reserve_tokens
        assert wire["store"] is False
        assert all(
            t["type"] == "function" and "function" not in t and t["strict"] is False
            for t in wire["tools"]
        )
        if len(wires) == 1:
            return httpx.Response(200, json=output(calls=True))
        inputs = wire["input"]
        assert any(item.get("encrypted_content") == "opaque-ciphertext" for item in inputs)
        assert {
            item["call_id"] for item in inputs if item.get("type") == "function_call_output"
        } == {"call_diff", "call_file"}
        assert any("VALUE = 2" in item.get("output", "") for item in inputs)
        return httpx.Response(200, json=output())

    async def scenario():
        provider = OpenAIProvider(store.blobs, cfg, transport=httpx.MockTransport(endpoint))
        try:
            return await run_review(
                store,
                cfg,
                {
                    "review_target": target,
                    "test_command": "python -m pytest -q",
                    "context": "Fix VALUE",
                },
                {**sandbox_config(), "image": image},
                [repository],
                provider=provider,
            )
        finally:
            await provider.close()

    try:
        result = asyncio.run(scenario())
        report = result["workspace_review"]
        assert result["status"] == "completed_unverified", result
        assert report["status"] == "approved", report
        assert report["audit"]["ok"] and report["checks_audit"]["ok"]
        assert len(wires) == 2
        usage = job_usage(root, {"run_id": result["run_id"], "kind": "workspace_review"})
        assert usage["totals"]["measured_review_tokens"] == 330
        assert usage["totals"]["measured_openai_cached"] == 14
        assert (repository / "value.py").read_text() == "VALUE = 1\n"
        assert (project / "value.py").read_text() == "VALUE = 2\n"
    finally:
        store.close()


def test_responses_wire_replay_images_compaction_and_local_compatibility(tmp_path, monkeypatch):
    cfg = review_config(monkeypatch)
    store = Store(tmp_path / "data")
    try:
        cfg = cfg.model_copy(update={"window_tokens": 32768, "output_reserve_tokens": 1024})
        fixed = [
            {"role": "system", "content": "Review"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Inspect"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AAAA", "detail": "high"},
                    },
                ],
            },
        ]
        snapshot, _ = ContextBuilder(store.blobs, cfg).build(
            fixed, [[{"role": "user", "content": "x" * 100000}]]
        )
        wire = store.blobs.json(snapshot.payload_ref)
        assert "messages" not in wire
        assert wire["input"][1]["content"][1]["type"] == "input_image"
        assert any("Older complete exchanges" in str(item) for item in wire["input"])
        assert snapshot.exclusions
        assert list(snapshot.messages) == wire["input"]
        assert list(snapshot.tool_definitions) == wire["tools"]
        local = cfg.model_copy(update={"base_url": "http://127.0.0.1:11434/v1"})
        assert not uses_responses(local)
        local_snapshot, _ = ContextBuilder(store.blobs, local).build(
            [{"role": "user", "content": "Task"}], []
        )
        assert "messages" in store.blobs.json(local_snapshot.payload_ref)
        replay = input_items([{"role": "assistant", "response_output": output()["output"]}])
        assert replay[-1]["phase"] == "final_answer"
    finally:
        store.close()


@pytest.mark.parametrize("failure", ["incomplete", "duplicate", "refusal"])
def test_responses_reject_incomplete_duplicate_and_refusal(failure):
    raw = output(calls=True)
    if failure == "incomplete":
        raw["status"] = "incomplete"
    elif failure == "duplicate":
        raw["output"][-1]["call_id"] = "call_diff"
    else:
        raw = output()
        raw["output"][-1]["content"] = [{"type": "refusal", "refusal": "Cannot comply"}]
    with pytest.raises(ValueError):
        normalize_response(raw)


def test_responses_malformed_arguments_remain_validation_proposals():
    result = normalize_response(output(calls=True, arguments="{broken"))
    assert result["tool_calls"][-1]["arguments"] == "{broken"
