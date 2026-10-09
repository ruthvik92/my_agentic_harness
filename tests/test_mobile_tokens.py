"""Accounting boundaries: provider counts, counterfactuals, images and failures."""

import base64
import io
from types import SimpleNamespace

from PIL import Image

from local_agent.mobile.token_totals import totals
from local_agent.mobile.tokens import (
    DEFAULT_BASELINE,
    encoding,
    estimate_openai,
    image_tokens,
    run_rows,
    summary,
)


def row(route="local", **values):
    return dict(
        route=route,
        input_tokens=500,
        output_tokens=100,
        estimated_openai_input=100,
        estimated_openai_output=20,
        kind="answer",
        **values,
    )


def test_review_overhead_can_exceed_savings_and_cached_tokens_are_subset():
    local = row()
    review = dict(
        route="openai", input_tokens=150, output_tokens=30, kind="review", cached_tokens=80
    )
    result = totals([local, review])
    assert result["measured_local_total"] == 600
    assert result["estimated_all_openai_baseline"] == 120
    assert result["measured_openai_total"] == 180
    assert result["measured_review_tokens"] == 180
    assert result["measured_openai_cached"] == 80
    assert result["estimated_net_saved_tokens"] == -60
    assert result["estimated_net_saved_percent"] == -50
    primary = dict(review, kind="answer")
    assert totals([primary])["estimated_net_saved_tokens"] == 0
    assert totals([local, primary])["estimated_net_saved_tokens"] == 120


def test_unknown_usage_does_not_become_zero_or_block_known_measurements():
    unknown = row()
    unknown["estimated_openai_input"] = None
    result = totals([unknown])
    assert result["measured_local_total"] == 600
    assert result["estimated_net_saved_tokens"] is None
    paid = dict(route="openai", input_tokens=50, output_tokens=None, kind="review")
    result = totals([row(), paid])
    assert result["measured_openai_input"] == 50
    assert result["unknown_openai_requests"] == 1
    assert result["estimated_net_saved_tokens"] is None
    paid["output_tokens"] = True
    assert totals([paid])["unknown_openai_requests"] == 1


def test_official_image_tiles_and_transport_are_not_text_tokens():
    assert image_tokens(1024, 1024, DEFAULT_BASELINE) == 765
    assert image_tokens(2048, 4096, DEFAULT_BASELINE) == 1105
    assert image_tokens(16, 16, DEFAULT_BASELINE) == 255
    assert image_tokens(4000, 4000, DEFAULT_BASELINE, "low") == 85
    assert image_tokens(1, 10000, DEFAULT_BASELINE) > 0
    assert image_tokens(1024, 1024, "gpt-4.1-mini") is None
    encoded = []
    for color in ("white", "black"):
        buffer = io.BytesIO()
        Image.new("RGB", (1024, 1024), color).save(buffer, format="PNG")
        encoded.append(base64.b64encode(buffer.getvalue()).decode())

    def estimate(image):
        return estimate_openai(
            [{"role": "user", "content": "Explain", "images": [image]}], "Answer", DEFAULT_BASELINE
        )

    first, second = map(estimate, encoded)
    assert first == second
    assert first["image_tokens"] == 765
    assert first["input"] < 800
    assert first["output"] == len(encoding(DEFAULT_BASELINE).encode("Answer"))


def test_failed_provider_response_usage_is_counted_without_inventing_answer():
    blobs = {
        "manifest": {"config_ref": "config"},
        "config": {"agent": {"model": DEFAULT_BASELINE, "base_url": "https://api.openai.com/v1"}},
        "bootstrap": {"provider": "harness"},
        "request": {"provider": "openai", "context_ref": "context"},
        "raw": {"usage": {"prompt_tokens": 21, "completion_tokens": 9}},
    }
    records = [
        {"id": "ignored", "request_ref": "bootstrap", "response_ref": None},
        {"id": "paid", "request_ref": "request", "response_ref": None},
    ]
    store = SimpleNamespace(
        run=lambda _: {"manifest_ref": "manifest"},
        blobs=SimpleNamespace(json=blobs.__getitem__),
        db=SimpleNamespace(execute=lambda *_: records),
        events=lambda _: [
            SimpleNamespace(
                event_type="model.failed", data={"request_id": "paid", "response_ref": "raw"}
            )
        ],
    )
    rows = run_rows(store, "run_test", "review", DEFAULT_BASELINE)
    assert len(rows) == 1
    assert totals(rows)["measured_openai_total"] == 30
    assert totals(rows)["estimated_net_saved_tokens"] == -30
    # Job snapshots are deduplicated and scoped to the selected owner thread.
    jobs = [
        {"thread_id": "one", "token_usage": {"rows": rows}},
        {"thread_id": "one", "token_usage": {"rows": rows}},
        {"thread_id": "two", "token_usage": {"rows": [dict(rows[0], request_id="other")]}},
    ]
    assert summary(jobs, "one")["totals"]["measured_openai_total"] == 30
    assert summary(jobs)["totals"]["measured_openai_total"] == 60


def test_owner_usage_routes_persist_accounting_and_trace_once(tmp_path, monkeypatch):
    from test_mobile_threads import catalog
    from test_mobile_web import completed, login, running

    from local_agent.mobile import web
    from local_agent.mobile.models import Models

    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    monkeypatch.setenv("OPENAI_API_KEY", "fake-verifier-not-called")
    rows = [
        dict(row(), request_id="req_local", run_id="run_local", baseline_model=DEFAULT_BASELINE)
    ]
    monkeypatch.setattr(web, "job_usage", lambda *_a: {"rows": rows, "totals": totals(rows)})
    root = tmp_path / "state"

    def runner(_):
        source = web.record(root, "a" * 32, "phone.feedback", {"vote": "up"})
        return {"status": "completed_unverified", "answer": "Visible answer", "run_id": source}

    with running(root, runner) as (server, client):
        assert client.get("/api/usage").status_code == 401
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Accounted chat"}).json()["thread_id"]
        endpoint = "/api/threads/" + tid
        jid = client.post(endpoint + "/ask", json={"question": "Explain"}).json()["job_id"]
        assert completed(client, jid)["token_usage"]["totals"]["estimated_net_saved_tokens"] == 120
        assert client.get(endpoint + "/usage").json()["totals"]["estimated_net_saved_tokens"] == 120
        assert client.get("/api/usage").json()["totals"]["estimated_net_saved_tokens"] == 120
        assert "fake-verifier-not-called" not in client.get("/api/usage").text
        events = client.get(endpoint + "/events").json()
        linked = [e for e in events if e["event_type"] == "phone.turn_linked"]
        assert len(linked) == 1
        assert linked[0]["data"]["token_usage"]["rows"][0]["request_id"] == "req_local"
        activity = client.get(endpoint).json()["activity_runs"]
    with running(root, runner) as (server, client):
        login(server, client)
        assert client.get(endpoint).json()["activity_runs"] == activity
        assert client.get("/api/usage").json()["totals"]["estimated_net_saved_tokens"] == 120
