"""Recover a recorded review after the known post-response capture-budget failure."""

from local_agent.mobile.activity import record
from local_agent.mobile.jobs import publish
from local_agent.storage.database import Store


def recover_review(root, job, threads):
    if (
        job.get("status") != "failed"
        or job.get("kind") != "review"
        or job.get("error") != "attempted tools"
        or not job.get("run_id")
        or not job.get("thread_id")
        or job.get("recovered_review")
    ):
        return False
    store = Store(root, readonly=True)
    try:
        if store.run(job["run_id"])["status"] != "budget_exhausted":
            return False
        events = store.events(job["run_id"])
        proposed = [
            e.data.get("response_ref") for e in events if e.event_type == "completion.proposed"
        ]
        if not proposed:
            return False
        ref = proposed[-1]
        response = store.blobs.json(ref)
        request = store.db.execute(
            "SELECT request_ref FROM model_requests WHERE run_id=? AND response_ref=?",
            (job["run_id"], ref),
        ).fetchone()
        if not request or store.blobs.json(request[0])["provider"] != "openai":
            return False
        if response.get("tool_calls") or not response.get("text"):
            return False
        text = response["text"]
    finally:
        store.close()
    note = "Recovered recorded OpenAI review. The original run failed after the model answered because the harness could not capture its final workspace diff. This is an UNVERIFIED advisory review; the original failed run is preserved."
    with threads._lock:
        thread_id = job["thread_id"]
        threads.add_exchange(
            thread_id,
            job["question"],
            note + "\n\n" + text,
            job["job_id"],
            job["run_id"],
            job["model"],
            "review",
        )
        thread = threads.get(thread_id)
        for message in thread["messages"]:
            if message.get("job_id") == job["job_id"]:
                message.update(
                    provider="openai", has_image=job.get("has_image", False), recovered=True
                )
        artifact = root / "phone/jobs" / job["job_id"] / "recovered-review.md"
        artifact.write_text(note + "\n\n" + text + "\n")
        artifact.chmod(0o600)
        activity = record(
            root,
            thread_id,
            "phone.review_recovered",
            {
                "job_id": job["job_id"],
                "source_run_id": job["run_id"],
                "response_ref": ref,
                "model": job["model"],
                "original_status": "budget_exhausted",
                "note": note,
            },
        )
        threads.update(
            thread_id,
            messages=thread["messages"],
            activity_runs=thread.get("activity_runs", []) + [activity],
        )
        job["recovered_review"] = {
            "activity_run_id": activity,
            "response_ref": ref,
            "artifact": "recovered-review.md",
        }
        publish(root / "phone/jobs" / job["job_id"] / "status.json", job)
    return True
