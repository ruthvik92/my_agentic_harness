from typing import Literal

from pydantic import Field, JsonValue

from local_agent.contracts import ID, Record, SpanID, TraceID

EventType = Literal[
    "run.created",
    "run.started",
    "run.resumed",
    "run.stopped",
    "context.built",
    "circuit.prepared",
    "screenshot.prepared",
    "phone.feedback",
    "phone.answer_feedback",
    "phone.turn_linked",
    "phone.usage_recorded",
    "phone.review_recovered",
    "circuit.netlist_generated",
    "context.compacted",
    "model.selected",
    "model.requested",
    "model.responded",
    "model.failed",
    "tool.proposed",
    "tool.validated",
    "tool.rejected",
    "tool.skipped",
    "policy.evaluated",
    "approval.requested",
    "approval.resolved",
    "execution.dispatch_intent",
    "execution.started",
    "execution.finished",
    "execution.reconciled",
    "memory.changed",
    "artifact.registered",
    "checkpoint.committed",
    "retry.decided",
    "cancel.requested",
    "budget.exhausted",
    "completion.proposed",
    "completion.verified",
    "workspace.prepared",
]


class Event(Record):
    event_id: ID
    run_id: ID
    run_seq: int = Field(ge=1)
    timestamp_utc: str
    trace_id: TraceID
    span_id: SpanID
    parent_span_id: SpanID | None
    event_type: EventType
    actor: str = Field(min_length=1, max_length=128)
    tool_call_id: ID | None = None
    caused_by: tuple[ID, ...] = ()
    data: dict[str, JsonValue]


TERMINAL = frozenset(
    {
        "verified",
        "completed_unverified",
        "failed",
        "cancelled",
        "budget_exhausted",
        "needs_reconciliation",
        "audit_unavailable",
    }
)
TRANSITIONS = {
    "created": {"running", "cancelled", "audit_unavailable"},
    "running": TERMINAL | {"waiting_approval"},
    "waiting_approval": {"running", "cancelled", "budget_exhausted", "audit_unavailable"},
}
