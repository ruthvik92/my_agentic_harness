from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider


class Spans:
    """Private SDK provider: no global exporter, payloads, or environment autoconfig."""

    def __init__(self):
        self.provider = TracerProvider(resource=Resource({"service.name": "local-agent"}))
        self.tracer = self.provider.get_tracer("local_agent", "0.1.0")

    @contextmanager
    def boundary(self, name: str):
        with self.tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as span:
            yield span

    def shutdown(self):
        self.provider.shutdown()


def correlation() -> dict:
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx.is_valid:
        raise RuntimeError("audit events require an active recording span")
    parent = getattr(span, "parent", None)
    return {
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
        "parent_span_id": f"{parent.span_id:016x}" if parent else None,
    }
