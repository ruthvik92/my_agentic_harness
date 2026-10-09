"""Reviewer discovery and request compatibility without paid inference."""

import json
from pathlib import Path

import httpx
import pytest

from local_agent.config import load_config
from local_agent.mobile.models import Models
from local_agent.runtime.context import ContextBuilder
from local_agent.storage.database import Store


def test_account_discovery_filters_supported_reviewers_and_keeps_key_private(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-private-key")
    original = httpx.Client

    def endpoint(request):
        assert request.url == "https://api.openai.com/v1/models"
        assert request.headers["authorization"] == "Bearer fake-private-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-6-astra"},
                    {"id": "gpt-6-luna"},
                    {"id": "text-embedding-3-large"},
                ]
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(endpoint)),
    )
    models = Models(load_config(Path("config/phone.yaml")))
    reviewer = models.review_catalog()
    assert reviewer["default_id"] == "openai:gpt-6-astra"
    assert {m["model"] for m in reviewer["models"] if m["selectable"]} == {
        "gpt-6-astra",
        "gpt-6-luna",
    }
    assert "fake-private-key" not in json.dumps(reviewer)
    assert all(m["vision"] and m["access_checked"] for m in reviewer["models"])
    monkeypatch.setattr(models, "catalog", lambda: {"verifier": reviewer})
    cfg = models.select_reviewer("openai:gpt-6-luna")
    assert cfg.model == "gpt-6-luna" and cfg.reasoning_effort == "medium"
    assert cfg.output_reserve_tokens == 16384
    with pytest.raises(ValueError, match="available OpenAI"):
        models.select_reviewer("openai:text-embedding-3-large")
    with pytest.raises(ValueError, match="available OpenAI"):
        models.select_reviewer("openai:gpt-4.1")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert not models.review_catalog()["enabled"]


def test_discovery_rejects_invalid_key_without_exposing_error_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-secret")
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(401, json={"error": "fake-secret"})
            ),
        ),
    )
    report = Models(load_config(Path("config/phone.yaml"))).review_catalog()
    assert not report["enabled"]
    assert "HTTP 401" in report["reason"]
    assert "fake-secret" not in json.dumps(report)


def test_reasoning_chat_request_uses_supported_parameters_and_budget(tmp_path):
    store = Store(tmp_path)
    try:
        cfg = load_config(Path("config/phone-verifier.yaml"))
        snapshot, _ = ContextBuilder(store.blobs, cfg).build(
            [{"role": "user", "content": "Review this circuit"}], []
        )
        payload = store.blobs.json(snapshot.payload_ref)
        assert payload["model"] == "gpt-6-astra"
        assert payload["reasoning_effort"] == "medium"
        assert payload["max_completion_tokens"] == 16384
        assert not {"temperature", "top_p", "tools", "think", "max_tokens"} & payload.keys()
        old = cfg.model_copy(update={"model": "gpt-4.1", "reasoning_effort": None})
        snapshot, _ = ContextBuilder(store.blobs, old).build(
            [{"role": "user", "content": "Review"}], []
        )
        assert "reasoning_effort" not in store.blobs.json(snapshot.payload_ref)
    finally:
        store.close()
