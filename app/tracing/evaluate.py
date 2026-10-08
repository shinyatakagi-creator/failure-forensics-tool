import json
import re

from app.pipeline import llm
from app.storage.db import get_span_attrs, max_step_latency
from app.storage.traces import read_trace_file
from app.tracing.tracer import tracer

LATENCY_THRESHOLD_MS = 8000
MIN_ANSWER_LEN = 10
MIN_GROUNDEDNESS = 3

JUDGE_SYSTEM = (
    "You are a strict grading judge. An answer is grounded if its claims come from the retrieved "
    "context OR the tool result. An answer derived from the tool result counts as grounded even "
    "when the context is unrelated."
)


def evaluate_run(trace_id: str, answer: str | None, error: str | None) -> tuple[bool, str | None]:
    for t in get_span_attrs(trace_id, "call_tool") + get_span_attrs(trace_id, "inspect_logs"):
        if t.get("tool.status") in ("error", "empty"):
            return True, f"tool {t['tool.status']}: {t.get('tool.name')} {t.get('tool.error', '')}".strip()
    if error:
        return True, f"exception: {error}"
    if not answer or len(answer.strip()) < MIN_ANSWER_LEN:
        return True, "empty or degenerate output"
    bad = _uncited_evidence(trace_id)
    if bad:
        return True, f"evidence not in logs: {bad[0]}"
    if max_step_latency(trace_id) > LATENCY_THRESHOLD_MS:
        return True, "step latency exceeded threshold"
    score, why = _judge_groundedness(trace_id, answer)
    if score < MIN_GROUNDEDNESS:
        return True, f"low groundedness score ({score}/5): {why}"
    return False, None


def _uncited_evidence(trace_id: str) -> list[str]:
    """Triage only: every evidence line a diagnosis cites must be a line search_logs returned."""
    diag = get_span_attrs(trace_id, "propose_diagnosis")
    if not diag:
        return []
    logs = ((read_trace_file(trace_id) or {}).get("tool_result") or {}).get("lines", [])
    cited = [e for c in json.loads(diag[0]["diagnosis"]).get("candidates", []) for e in c.get("evidence", [])]
    return [e for e in cited if e.strip() not in logs]


def _judge_groundedness(trace_id: str, answer: str) -> tuple[int, str]:
    trace = read_trace_file(trace_id) or {}
    context = trace.get("context") or ""
    tool_result = trace.get("tool_result")
    with tracer.start_as_current_span("judge_groundedness") as span:
        if llm.HAS_API_KEY:
            span.set_attribute("judge.model", llm.JUDGE_MODEL)
            verdict = llm.complete(
                f"Context:\n{context}\n\nTool result:\n{tool_result}\n\nAnswer:\n{answer}\n\n"
                "Score 1-5 how well the answer is grounded. Reply exactly as:\n"
                "SCORE: <digit>\nREASON: <one line>",
                system=JUDGE_SYSTEM,
                model=llm.JUDGE_MODEL,
            )
            m = re.search(r"SCORE:\s*([1-5])", verdict)
            r = re.search(r"REASON:\s*(.+)", verdict)
            score, why = (int(m.group(1)), r.group(1).strip() if r else "") if m else (3, "unparseable judge output")
        else:
            # ponytail: no API key -> word-overlap heuristic instead of a real LLM judge.
            # upgrade: set OPENAI_API_KEY to use the real grading prompt above.
            ctx_words = set(f"{context} {tool_result or ''}".lower().split())
            ans_words = set(answer.lower().split())
            overlap = len(ctx_words & ans_words) / len(ans_words) if ans_words else 0
            score, why = max(1, min(5, round(overlap * 5))), "word-overlap heuristic"
        span.set_attribute("judge.score", score)
        span.set_attribute("judge.reason", why)
        return score, why
