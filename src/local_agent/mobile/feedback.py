"""Answer-specific feedback with immutable model/run attribution for future routing."""

from local_agent.mobile.activity import record


def answer_feedback(root, threads, thread_id, answer_id, vote):
    if vote not in (None, "up", "down"):
        raise ValueError("Feedback must be up, down or null")
    with threads._lock:
        thread = threads.get(thread_id)
        message = next(
            (
                m
                for m in thread["messages"]
                if m.get("role") == "assistant" and m.get("job_id") == answer_id
            ),
            None,
        )
        if message is None:
            raise ValueError("Answer not found in this thread")
        previous = message.get("feedback")
        if previous == vote:
            return thread
        kind = message.get("kind", "answer")
        stage = (
            "vision"
            if kind == "answer" and message.get("has_image")
            else "chat"
            if kind == "answer"
            else kind
        )
        activity = record(
            root,
            thread_id,
            "phone.answer_feedback",
            {
                "feedback_schema_version": 1,
                "owner": thread["owner"],
                "answer_id": answer_id,
                "job_id": answer_id,
                "source_run_id": message.get("run_id"),
                "model": message.get("model"),
                "provider": message.get("provider"),
                "stage": stage,
                "kind": kind,
                "has_image": bool(message.get("has_image")),
                "recovered": bool(message.get("recovered")),
                "answer_created": message.get("created"),
                "vote": vote,
                "previous_vote": previous,
            },
        )
        message.update(feedback=vote, feedback_activity_run=activity)
        return threads.update(
            thread_id,
            messages=thread["messages"],
            activity_runs=thread.get("activity_runs", []) + [activity],
        )
