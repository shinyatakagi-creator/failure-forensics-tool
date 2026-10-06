import os

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter

from app.storage.db import insert_span


class SQLiteSpanProcessor(SpanProcessor):
    def on_end(self, span):
        ctx = span.get_span_context()
        parent = span.parent.span_id if span.parent else None
        insert_span({
            "span_id": format(ctx.span_id, "016x"),
            "trace_id": format(ctx.trace_id, "032x"),
            "parent_span_id": format(parent, "016x") if parent else None,
            "name": span.name,
            "started_at": span.start_time,
            "ended_at": span.end_time,
            "status": span.status.status_code.name,
            "attributes": dict(span.attributes or {}),
            "latency_ms": (span.end_time - span.start_time) / 1e6,
        })


provider = TracerProvider()
provider.add_span_processor(SQLiteSpanProcessor())
if os.environ.get("FF_CONSOLE_TRACES"):
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("failure-forensics")
