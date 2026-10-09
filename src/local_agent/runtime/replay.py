"""Read-only reducer shared by trace inspection and recorded replay; no executor imports."""

from dataclasses import dataclass, field

from local_agent.observability.events import TRANSITIONS


@dataclass
class RecordedState:
    status: str | None = None
    model_turns: int = 0
    attempted_calls: int = 0
    pending: set[str] = field(default_factory=set)
    rejected: int = 0
    denied: int = 0
    finished: int = 0

    def apply(self, event, blobs):
        kind = event.event_type
        if kind == "run.created":
            if self.status is not None:
                raise ValueError("duplicate run creation")
            self.status = "created"
        elif kind == "run.resumed":
            if self.status != "running":
                raise ValueError("resume requires a nonterminal running state")
        elif kind in {"run.started", "run.stopped"}:
            target = event.data["status"]
            if target not in TRANSITIONS.get(self.status, set()):
                raise ValueError(f"invalid recorded transition {self.status} -> {target}")
            self.status = target
        elif kind == "model.requested":
            self.model_turns += 1
        elif kind in {"tool.validated", "tool.rejected"}:
            self.attempted_calls += 1
            self.rejected += kind == "tool.rejected"
        elif kind == "policy.evaluated":
            self.denied += blobs.json(event.data["decision_ref"])["verdict"] == "deny"
        elif kind == "execution.dispatch_intent":
            execution_id = event.data["execution_id"]
            if execution_id in self.pending:
                raise ValueError("duplicate dispatch")
            self.pending.add(execution_id)
        elif kind in {"execution.finished", "execution.reconciled"}:
            execution_id = event.data["execution_id"]
            if execution_id not in self.pending:
                raise ValueError("terminal execution lacks dispatch")
            if event.data.get("result_ref") is not None:
                self.pending.remove(execution_id)
                self.finished += 1


def recorded_replay(store, run_id):
    replay_boundaries(store, run_id)
    state = RecordedState()
    for event in store.events(run_id):
        state.apply(event, store.blobs)
    return {
        "run_id": run_id,
        "status": state.status,
        "model_turns": state.model_turns,
        "attempted_calls": state.attempted_calls,
        "rejected": state.rejected,
        "denied": state.denied,
        "finished": state.finished,
        "pending_execution_ids": sorted(state.pending),
        "real_tools_executed": 0,
        "mode": "recorded-only",
        "capture_mode": "full",
    }


class CapturedProvider:
    """Provider interface backed exclusively by durable response records."""

    def __init__(self, store):
        self.store = store

    def generate(self, request_id):
        from local_agent.contracts import ModelResponse

        row = self.store.db.execute(
            "SELECT response_ref FROM model_requests WHERE id=?", (request_id,)
        ).fetchone()
        return ModelResponse.model_validate_json(self.store.blobs.read(row[0])) if row[0] else None


class CapturedExecutor:
    """Consumes recorded outcomes; deliberately has no execution backend."""

    def __init__(self, store):
        self.store = store

    def execute(self, execution_id):
        from local_agent.contracts import ExecutionResult

        row = self.store.db.execute(
            "SELECT result_ref FROM execution_attempts WHERE id=?", (execution_id,)
        ).fetchone()
        return (
            ExecutionResult.model_validate_json(self.store.blobs.read(row[0])) if row[0] else None
        )


def replay_boundaries(store, run_id):
    provider, executor = CapturedProvider(store), CapturedExecutor(store)
    for event in store.events(run_id):
        if event.event_type == "model.responded":
            response = provider.generate(event.data["request_id"])
            if response is None or response.request_id != event.data["request_id"]:
                raise ValueError("captured provider response mismatch")
        elif event.event_type in {"execution.finished", "execution.reconciled"}:
            result = executor.execute(event.data["execution_id"])
            if event.data.get("result_ref") and (
                result is None or result.execution_id != event.data["execution_id"]
            ):
                raise ValueError("captured executor outcome mismatch")
