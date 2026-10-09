from local_agent.observability.events import TERMINAL
from local_agent.observability.spans import Spans


async def cancel(store, run_id):
    status = store.run(run_id)["status"]
    if status in TERMINAL:
        return {"run_id": run_id, "status": status, "cancel_requested": False}
    spans = Spans()
    try:
        with spans.boundary("cancel.request"):
            prior = store.events(run_id)[-1]
            store.append(
                run_id,
                "cancel.requested",
                "user",
                {"reason": "CLI cancellation"},
                causes=(prior.event_id,),
            )
        return {"run_id": run_id, "status": status, "cancel_requested": True}
    finally:
        spans.shutdown()
