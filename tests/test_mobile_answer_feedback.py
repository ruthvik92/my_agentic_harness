"""Answer feedback attribution, persistence, isolation, audit and vote changes."""

import base64

from test_mobile_runtime import screenshot
from test_mobile_threads import catalog
from test_mobile_web import completed, login, running

from local_agent.mobile.models import Models
from local_agent.observability.audit import audit
from local_agent.storage.database import Store


def test_answer_feedback_is_attributed_and_independent_of_thread_vote(tmp_path, monkeypatch):
    monkeypatch.setattr(Models, "catalog", lambda *_a, **_k: catalog())
    monkeypatch.setenv("OPENAI_API_KEY", "fake-no-inference")

    def runner(_):
        return {"status": "completed_unverified", "answer": "**Unverified** answer"}

    root = tmp_path / "state"
    with running(
        root, runner, verifier_path="examples/configs/openai-reviewer.yaml"
    ) as (server, client):
        assert (
            client.post(
                "/api/threads/" + "a" * 32 + "/answers/" + "b" * 32 + "/feedback",
                json={"vote": "up"},
            ).status_code
            == 401
        )
        login(server, client)
        tid = client.post("/api/threads", json={"title": "Feedback"}).json()["thread_id"]
        endpoint = "/api/threads/" + tid
        job = client.post(
            endpoint + "/ask",
            json={"question": "Read", "image": base64.b64encode(screenshot()).decode()},
        ).json()["job_id"]
        assert completed(client, job)["status"] == "completed"
        netlist = client.post(
            endpoint + "/netlist", json={"model_id": "ollama:glm-4.7-flash:q8_0"}
        ).json()["job_id"]
        assert completed(client, netlist)["status"] == "completed"
        review = client.post(endpoint + "/review", json={"model_id": "openai:gpt-6-luna"}).json()[
            "job_id"
        ]
        assert completed(client, review)["status"] == "completed"
        client.post(endpoint + "/feedback", json={"vote": "up"})
        target = endpoint + "/answers/" + job + "/feedback"
        first = client.post(target, json={"vote": "down"})
        assert first.status_code == 200, first.text
        message = next(m for m in first.json()["messages"] if m.get("job_id") == job)
        assert message["feedback"] == "down" and "rendered_html" in message
        activities = first.json()["activity_runs"]
        assert client.post(target, json={"vote": "down"}).json()["activity_runs"] == activities
        assert client.post(target, json={"vote": "bad"}).status_code == 400
        assert client.post(target, json={"vote": "up", "model": "fake"}).status_code == 400
        other = client.post("/api/threads", json={"title": "Other"}).json()["thread_id"]
        assert (
            client.post(
                "/api/threads/" + other + "/answers/" + job + "/feedback", json={"vote": "up"}
            ).status_code
            == 400
        )
        for answer, vote in ((job, "up"), (job, None), (netlist, "up"), (review, "down")):
            reply = client.post(endpoint + "/answers/" + answer + "/feedback", json={"vote": vote})
            assert reply.status_code == 200, reply.text
        chat_endpoint = "/api/threads/" + other
        chat = client.post(chat_endpoint + "/ask", json={"question": "Text question"}).json()[
            "job_id"
        ]
        assert completed(client, chat)["status"] == "completed"
        assert (
            client.post(
                chat_endpoint + "/answers/" + chat + "/feedback", json={"vote": "up"}
            ).status_code
            == 200
        )
        chat_events = [
            e
            for e in client.get(chat_endpoint + "/events").json()
            if e["event_type"] == "phone.answer_feedback"
        ]
        assert chat_events[0]["data"]["stage"] == "chat"
        events = [
            e
            for e in client.get(endpoint + "/events").json()
            if e["event_type"] == "phone.answer_feedback"
        ]
        assert len(events) == 5
        first_event = events[0]["data"]
        assert first_event["answer_id"] == job and first_event["job_id"] == job
        assert first_event["model"] == "qwen3.8:27b"
        assert first_event["provider"] == "ollama" and first_event["stage"] == "vision"
        assert first_event["owner"] == "local-owner" and first_event["previous_vote"] is None
        assert events[1]["data"]["previous_vote"] == "down"
        assert events[2]["data"]["vote"] is None
        assert (
            events[3]["data"]["model"] == "glm-4.7-flash:q8_0"
            and events[3]["data"]["stage"] == "netlist"
        )
        assert events[4]["data"]["provider"] == "openai" and events[4]["data"]["stage"] == "review"
        store = Store(root)
        try:
            for e in events:
                assert audit(store, e["run_id"])["ok"]
        finally:
            store.close()
        saved = client.get(endpoint).json()
        assert saved["feedback"] == "up"
        assert [m["feedback"] for m in saved["messages"] if m["role"] == "assistant"] == [
            None,
            "up",
            "down",
        ]
        assert all(set(m) == {"role", "content"} for m in server.threads.history(tid))
    with running(root, runner) as (server, client):
        login(server, client)
        saved = client.get(endpoint).json()
        assert [m["feedback"] for m in saved["messages"] if m["role"] == "assistant"] == [
            None,
            "up",
            "down",
        ]
        assert (
            len(
                [
                    e
                    for e in client.get(endpoint + "/events").json()
                    if e["event_type"] == "phone.answer_feedback"
                ]
            )
            == 5
        )


def test_answer_vote_preserves_original_run_and_recovered_provenance(tmp_path):
    from local_agent.mobile.activity import record
    from local_agent.mobile.feedback import answer_feedback
    from local_agent.mobile.threads import Threads

    threads = Threads(tmp_path)
    tid = threads.create("Recovered review")
    source = record(tmp_path, tid, "phone.turn_linked", {"kind": "review"})
    answer_id = "c" * 32
    threads.add_exchange(
        tid, "Review", "Recorded answer", answer_id, source, "gpt-6.1-sol", "review"
    )
    thread = threads.get(tid)
    thread["messages"][-1].update(provider="openai", recovered=True)
    threads.update(tid, messages=thread["messages"])
    store = Store(tmp_path, readonly=True)
    before = [e.model_dump() for e in store.events(source)]
    try:
        saved = answer_feedback(tmp_path, threads, tid, answer_id, "up")
        assert [e.model_dump() for e in store.events(source)] == before
        assert store.run(source)["status"] == "completed_unverified"
        activity = saved["messages"][-1]["feedback_activity_run"]
        event = next(e for e in store.events(activity) if e.event_type == "phone.answer_feedback")
        assert event.data["source_run_id"] == source
        assert event.data["recovered"] is True
        assert event.data["stage"] == "review" and event.data["model"] == "gpt-6.1-sol"
        assert audit(store, activity)["ok"]
    finally:
        store.close()
