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
    models = Models(
        load_config(Path("config/browser.yaml")),
        verifier_path=Path("examples/configs/openai-reviewer.yaml"),
    )
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
    report = Models(
        load_config(Path("config/browser.yaml")),
        verifier_path=Path("examples/configs/openai-reviewer.yaml"),
    ).review_catalog()
    assert not report["enabled"]
    assert "HTTP 401" in report["reason"]
    assert "fake-secret" not in json.dumps(report)


def test_reasoning_chat_request_uses_supported_parameters_and_budget(tmp_path):
    store = Store(tmp_path)
    try:
        cfg = load_config(Path("examples/configs/openai-reviewer.yaml"))
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


@pytest.mark.parametrize("mode", ["chat", "coding", "circuit"])
def test_saved_task_review_across_modes(tmp_path, monkeypatch, mode):
    from test_mobile_threads import catalog
    from test_mobile_web import completed, login, running

    monkeypatch.setenv("OPENAI_API_KEY", "fake-private-key")
    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    captured = []

    def runner(path):
        captured.append(json.loads(path.read_text()))
        return {"status": "completed_unverified", "answer": "Advisory review"}

    with running(tmp_path, runner, verifier_path="examples/configs/openai-reviewer.yaml") as (
        server,
        client,
    ):
        login(server, client)
        tid = server.threads.create(mode)
        endpoint = f"/api/threads/{tid}/review"
        assert client.post(endpoint, json={}).status_code == 400
        assert not captured
        server.threads.add_exchange(
            tid, "Check my task", "Reported success", "saved", None, "local"
        )
        thread = server.threads.get(tid)
        thread["messages"][-1].update(
            mode=mode,
            workspace="/untrusted/workspace",
            diff_ref="blob:claimed-diff",
            git_workspace={"candidate_commit": "claimed-commit", "branch": "x" * 10000},
        )
        server.threads.update(tid, messages=thread["messages"])
        for _ in range(2):
            response = client.post(endpoint, json={"model_id": "openai:gpt-6-luna"})
            assert response.status_code == 202, response.text
            assert completed(client, response.json()["job_id"])["status"] == "completed"
            request = captured[-1]
            assert "no filesystem access" in request["question"]
            assert "cannot inspect workspace files or run tests" in request["question"]
            assert "claimed-commit" in request["question"]
            assert f'"mode": "{mode}"' in request["question"]
            assert len(request["question"]) < 8000
            assert "image" not in request
            assert request["history"][-1]["role"] == "assistant"
        assert "fake-private-key" not in json.dumps(captured)


def test_review_disabled_without_verifier_profile(tmp_path):
    from test_mobile_web import login, running

    def runner(path):
        pytest.fail("Disabled review must not invoke a runner")

    with running(tmp_path, runner) as (server, client):
        login(server, client)
        tid = server.threads.create("Saved coding task")
        server.threads.add_exchange(tid, "q", "a", "saved", None, "local")
        response = client.post(f"/api/threads/{tid}/review", json={})
        assert response.status_code == 400
        assert "--verifier-agent" in response.json()["error"]
        assert server.models.review_catalog()["enabled"] is False


def test_failed_workspace_review_preserves_test_output_in_saved_chat(tmp_path):
    from test_mobile_web import completed, login, running

    report = {
        "status": "failed",
        "target": {"candidate_commit": "candidate"},
        "checks_passed": False,
        "checks": [{"exit_code": 4, "output": "ModuleNotFoundError: local_agent"}],
    }

    def runner(path):
        return {
            "status": "failed",
            "answer": "Reviewer did not complete.",
            "error": "OpenAI HTTP status 400",
            "workspace_review": report,
        }

    with running(tmp_path, runner) as (server, client):
        login(server, client)
        tid = server.threads.create("Failed review")
        jid = server.jobs.submit(
            {"question": "Verify"},
            metadata={"thread_id": tid, "question": "Verify", "kind": "workspace_review"},
        )
        assert completed(client, jid)["status"] == "failed"
        saved = client.get(f"/api/threads/{tid}").json()
        assert "OpenAI HTTP status 400" in saved["messages"][-1]["content"]
        assert saved["messages"][-1]["workspace_review"]["checks"][0]["exit_code"] == 4
        assert client.get(f"/api/jobs/{jid}/workspace-review").json() == report

    def no_replay(path):
        pytest.fail("Restart must not retry a failed paid review")

    with running(tmp_path, no_replay) as (server, client):
        login(server, client)
        saved = client.get(f"/api/threads/{tid}").json()
        assert len(saved["messages"]) == 2
        assert saved["messages"][-1]["workspace_review"] == report


def test_reviewer_selection_honors_operator_output_allowance(monkeypatch):
    models = Models(load_config(Path('config/browser.yaml')), 'examples/configs/openai-reviewer.yaml')
    cfg = models.verifier_config().model_copy(update={'output_reserve_tokens': 4096})
    monkeypatch.setattr(models, 'verifier_config', lambda: cfg)
    monkeypatch.setattr(models, 'catalog', lambda: {'verifier': {'models': [
        {'id': 'openai:gpt-6-luna', 'model': 'gpt-6-luna', 'selectable': True},
    ]}})
    assert models.select_reviewer('openai:gpt-6-luna', workspace=True).output_reserve_tokens == 4096
