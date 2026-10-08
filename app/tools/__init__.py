import os

from opentelemetry import trace


def fault() -> str | None:
    """Deliberate fault for Phase 12 evals: remove_logs | wrong_doc | tool_throws | truncate_reply | fabricate_evidence."""
    return os.environ.get("TRIAGE_FAULT")


def mark(name: str, status: str, error: str | None = None) -> None:
    """Set tool.* attributes on the current span (the caller's step span)."""
    span = trace.get_current_span()
    span.set_attribute("tool.name", name)
    span.set_attribute("tool.status", status)
    if error:
        span.set_attribute("tool.error", error)
