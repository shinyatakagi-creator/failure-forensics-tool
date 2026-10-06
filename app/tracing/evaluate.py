from app.pipeline import llm
from app.storage.db import max_step_latency
from app.storage.traces import read_trace_file

LATENCY_THRESHOLD_MS = 8000
MIN_ANSWER_LEN = 10
MIN_GROUNDEDNESS = 3


def evaluate_run(trace_id: str, answer: str | None, error: str | None) -> tuple[bool, str | None]:
    if error:
        return True, f"exception: {error}"
    if not answer or len(answer.strip()) < MIN_ANSWER_LEN:
        return True, "empty or degenerate output"
    if max_step_latency(trace_id) > LATENCY_THRESHOLD_MS:
        return True, "step latency exceeded threshold"
    score = _judge_groundedness(trace_id, answer)
    if score < MIN_GROUNDEDNESS:
        return True, f"low groundedness score ({score}/5)"
    return False, None


def _judge_groundedness(trace_id: str, answer: str) -> int:
    trace = read_trace_file(trace_id) or {}
    context = trace.get("context") or ""
    if llm.HAS_API_KEY:
        verdict = llm.complete(
            f"Context:\n{context}\n\nAnswer:\n{answer}\n\n"
            "Score 1-5 how well the answer is grounded in the context. Reply with only the digit.",
            system="You are a strict grading judge.",
        )
        try:
            return int(verdict.strip()[0])
        except (ValueError, IndexError):
            return 3
    # ponytail: no API key -> word-overlap heuristic instead of a real LLM judge.
    # upgrade: set OPENAI_API_KEY to use the real grading prompt above.
    context_words = set(context.lower().split())
    answer_words = set(answer.lower().split())
    if not answer_words:
        return 1
    overlap = len(context_words & answer_words) / len(answer_words)
    return max(1, min(5, round(overlap * 5)))
