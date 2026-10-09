"""Controller verification of the harness draft and persistent browser workflow."""

import base64
import json

import pytest
from test_mobile_runtime import screenshot
from test_mobile_web import completed, login, running

from local_agent.mobile.models import Models
from local_agent.mobile.threads import Threads
from local_agent.observability.audit import audit
from local_agent.storage.database import Store


def catalog():
    return {
        "models": [
            {
                "id": "ollama:qwen3.8:27b",
                "model": "qwen3.8:27b",
                "provider": "ollama",
                "selectable": True,
                "vision": True,
                "capabilities": ["completion", "vision"],
            },
            {
                "id": "ollama:glm-4.7-flash:q8_0",
                "model": "glm-4.7-flash:q8_0",
                "provider": "ollama",
                "selectable": True,
                "vision": False,
                "capabilities": ["completion", "tools"],
            },
        ],
        "default_id": "ollama:qwen3.8:27b",
        "error": None,
        "verifier": {
            "model": "gpt-6-astra",
            "default_id": "openai:gpt-6-astra",
            "enabled": True,
            "reason": None,
            "models": [
                {
                    "id": "openai:" + model,
                    "model": model,
                    "provider": "openai",
                    "capabilities": ["completion", "vision", "reasoning"],
                    "vision": True,
                    "selectable": True,
                }
                for model in ("gpt-6-astra", "gpt-6-luna", "gpt-4.1-2025-04-14")
            ],
        },
    }


def test_thread_history_idempotence_and_storage_boundaries(tmp_path):
    threads = Threads(tmp_path)
    tid = threads.create("Original")
    for index in range(5):
        threads.add_exchange(tid, f"Question {index}", f"Answer {index}", str(index), None, "local")
    threads.add_exchange(tid, "duplicate", "duplicate", "4", None, "local")
    assert len(threads.get(tid)["messages"]) == 10
    assert len(threads.history(tid)) == 6
    assert threads.history(tid)[0]["content"] == "Question 2"
    threads.add_exchange(tid, "q" * 8000, "a" * 20000, "long", None, "local")
    assert [m["role"] for m in threads.history(tid)] == ["user", "assistant"]
    assert sum(len(m["content"]) for m in threads.history(tid)) == 16000
    threads.update_image(tid, "image", "image/png")
    assert "image" not in threads.recent()[0]
    assert Threads(tmp_path).get(tid)["image"] == "image"
    with pytest.raises(ValueError):
        threads.get("../config")
    with pytest.raises(ValueError):
        threads.create("x" * 161)
    linked = tmp_path / "phone/threads" / ("a" * 32)
    linked.symlink_to(tmp_path / "phone/threads" / tid, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        threads.get("a" * 32)


def test_models_memory_feedback_netlist_and_paid_review(tmp_path, monkeypatch):
    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-only-key")
    captured = []

    def runner(path):
        request = json.loads(path.read_text())
        cfg = json.loads(path.with_name("config.json").read_text())
        captured.append((request, cfg))
        return {"status": "completed_unverified", "answer": "Visible R1 and uncertain junction"}

    root = tmp_path / "state"
    with running(root, runner) as (server, client):
        assert client.get("/api/threads").status_code == 401
        login(server, client)
        assert "test-server-only-key" not in client.get("/api/models").text
        tid = client.post("/api/threads", json={"title": "Amplifier"}).json()["thread_id"]
        image = base64.b64encode(screenshot()).decode()
        endpoint = "/api/threads/" + tid
        assert client.post(endpoint + "/netlist", json={}).status_code == 400
        invalid = client.post(
            endpoint + "/ask",
            json={"question": "Read", "image": image, "model_id": "ollama:glm-4.7-flash:q8_0"},
        )
        assert invalid.status_code == 400 and "vision" in invalid.text
        first = client.post(endpoint + "/ask", json={"question": "Read", "image": image})
        assert first.status_code == 202, first.text
        first_id = first.json()["job_id"]
        assert completed(client, first_id)["status"] == "completed"
        follow = client.post(endpoint + "/ask", json={"question": "Why?"}).json()["job_id"]
        assert completed(client, follow)["status"] == "completed"
        assert captured[1][0]["history"] == [
            {"role": "user", "content": "Read"},
            {"role": "assistant", "content": "Visible R1 and uncertain junction"},
        ]
        assert captured[1][0]["image"] == image
        netlist = client.post(
            endpoint + "/netlist", json={"model_id": "ollama:glm-4.7-flash:q8_0"}
        ).json()["job_id"]
        assert completed(client, netlist)["model"] == "glm-4.7-flash:q8_0"
        assert "image" not in captured[-1][0]
        assert "Recorded VLM observations" in captured[-1][0]["question"]
        assert captured[-1][1]["model"] == "glm-4.7-flash:q8_0"
        assert (
            client.post(endpoint + "/review", json={"model_id": "ollama:qwen3.8:27b"}).status_code
            == 400
        )
        review = client.post(endpoint + "/review", json={"model_id": "openai:gpt-6-luna"}).json()[
            "job_id"
        ]
        assert completed(client, review)["provider"] == "openai"
        assert captured[-1][1]["model"] == "gpt-6-luna"
        assert captured[-1][1]["reasoning_effort"] == "medium"
        assert captured[-1][1]["output_reserve_tokens"] == 16384
        assert captured[-1][0]["image"] == image
        assert captured[-1][0]["history"][-1]["content"] == "Visible R1 and uncertain junction"
        feedback = client.post(endpoint + "/feedback", json={"vote": "up"})
        assert feedback.status_code == 200, feedback.text
        activities = feedback.json()["activity_runs"]
        assert (
            client.post(endpoint + "/feedback", json={"vote": "up"}).json()["activity_runs"]
            == activities
        )
        events = client.get(endpoint + "/events").json()
        assert any(
            e["event_type"] == "phone.feedback" and e["data"]["vote"] == "up" for e in events
        )
        assert any(
            e["event_type"] == "phone.turn_linked" and e["data"]["kind"] == "review" for e in events
        )
        store = Store(root)
        try:
            for run_id in activities:
                assert audit(store, run_id)["ok"]
        finally:
            store.close()
        assert len(client.get(endpoint).json()["messages"]) == 8
        monkeypatch.delenv("OPENAI_API_KEY")
        assert client.post(endpoint + "/review", json={}).status_code == 400
        assert len(captured) == 4

    def no_replay(path):
        pytest.fail("Restart re-ran a completed request")

    with running(root, no_replay) as (server, client):
        login(server, client)
        saved = client.get(endpoint).json()
        assert saved["image"] == image and saved["feedback"] == "up"
        assert len(saved["messages"]) == 8
        assert client.get("/api/threads").json()[0]["thread_id"] == tid


def test_legacy_jobs_imported_once(tmp_path):
    def runner(path):
        return {"status": "completed_unverified", "answer": "Old answer"}

    root = tmp_path / "state"
    with running(root, runner) as (server, client):
        login(server, client)
        job = client.post("/api/ask", json={"question": "Old question"}).json()["job_id"]
        assert completed(client, job)["status"] == "completed"
    for _ in range(2):
        with running(root, runner) as (server, client):
            login(server, client)
            threads = client.get("/api/threads").json()
            assert len(threads) == 1
            thread = client.get("/api/threads/" + threads[0]["thread_id"]).json()
            assert [m["content"] for m in thread["messages"]] == ["Old question", "Old answer"]
