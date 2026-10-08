import datetime
import json
import pathlib
import re

from app.guardrails import check_kill_switch, redact
from app.pipeline import llm
from app.pipeline.docs import search_docs
from app.storage.db import insert_run
from app.storage.traces import write_trace_file
from app.tools import fault
from app.tools.logs import search_logs
from app.tracing.evaluate import evaluate_run
from app.tracing.tracer import tracer

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
DEFAULT_PATTERN = "ERROR|WARN|FATAL"


def _json(prompt: str, fallback):
    """Ask the model for JSON; offline or on bad output use the deterministic fallback."""
    # ponytail: offline fallback is a naive heuristic, not reasoning. Set OPENAI_API_KEY for the real agent.
    if not llm.HAS_API_KEY:
        return fallback
    try:
        text = llm.complete(prompt + "\nReply with JSON only.")
        return json.loads(text[text.index("{"):text.rindex("}") + 1])
    except ValueError:
        return fallback


def classify_ticket(symptom: str, area: str) -> dict:
    with tracer.start_as_current_span("classify_ticket") as span:
        span.set_attribute("input", symptom)
        out = _json(f"Ticket: {symptom}\nGive JSON {{\"area\": ..., \"severity\": low|medium|high}}.",
                    {"area": area, "severity": "medium"})
        span.set_attribute("output_preview", json.dumps(out))
        return out


def retrieve_docs(symptom: str) -> str:
    with tracer.start_as_current_span("retrieve_docs") as span:
        span.set_attribute("input", symptom)
        doc = search_docs(symptom, DATA / "triage_docs")
        if fault() == "wrong_doc":
            doc = (DATA / "triage_docs" / "status_codes.md").read_text()
        span.set_attribute("output_preview", doc[:300])
        return doc


def inspect_logs(ticket_id: str, symptom: str) -> dict:
    with tracer.start_as_current_span("inspect_logs") as span:
        pattern = _json(
            f"Ticket: {symptom}\n"
            "Log lines look like '<timestamp> <LEVEL> <message with key=value pairs>', LEVEL is DEBUG/INFO/WARN/ERROR. "
            "Do NOT search for the ticket's own wording. Pick a short regex of likely log keywords for the underlying "
            "cause, e.g. 'ERROR|WARN|timeout|expired|limit'. Reply as JSON with one key, \"pattern\".",
            {"pattern": DEFAULT_PATTERN}).get("pattern") or DEFAULT_PATTERN
        span.set_attribute("input", pattern)
        result = search_logs(ticket_id, pattern)
        result["lines"] = [redact(l) for l in result["lines"]]
        span.set_attribute("output_preview", "\n".join(result["lines"])[:300])
        return result


def propose_diagnosis(symptom: str, doc: str, lines: list[str]) -> dict:
    with tracer.start_as_current_span("propose_diagnosis") as span:
        fallback = {"candidates": [{"cause": re.sub(r"^\S+ ", "", l), "evidence": [l]} for l in lines if " ERROR " in l][:2]}
        out = _json(f"Ticket: {symptom}\nDoc: {doc}\nLog lines:\n" + "\n".join(lines) +
                    "\nGive JSON {\"candidates\": [{\"cause\": ..., \"evidence\": [exact log lines]}]}. "
                    "Evidence must be copied verbatim from the log lines above. If there are no log lines, "
                    "return {\"candidates\": []}; never invent evidence.", fallback)
        if fault() == "fabricate_evidence":
            for c in out.get("candidates", []):
                c["evidence"] = ["2023-10-23T08:15:00Z ERROR upstream dependency returned 500"]
        span.set_attribute("diagnosis", json.dumps(out))
        return out


def draft_reply(symptom: str, diagnosis: dict) -> str:
    with tracer.start_as_current_span("draft_reply") as span:
        cands = diagnosis.get("candidates") or []
        cause = cands[0]["cause"] if cands else "we are still investigating"
        if llm.HAS_API_KEY:
            reply = llm.complete(f"Ticket: {symptom}\nLikely cause: {cause}\nWrite a short, polite customer reply. "
                                 "Do not promise refunds or dates.", system="You are a support agent drafting for human review.")
        else:
            reply = f"Hi, thanks for reporting this. Our investigation points to: {cause}. We are working on it and will update you."
        if fault() == "truncate_reply":
            reply = reply[: len(reply) * 2 // 5]
        span.set_attribute("output_preview", reply[:300])
        return reply


def await_approval() -> None:
    with tracer.start_as_current_span("await_approval") as span:
        span.set_attribute("output_preview", "pending_approval")  # nothing is ever sent from here


def run_triage(ticket_id: str) -> dict:
    check_kill_switch()
    ticket = json.loads((DATA / "tickets" / f"{pathlib.Path(ticket_id).name}.json").read_text())
    symptom = redact(ticket["symptom"])
    with tracer.start_as_current_span("run") as run_span:
        trace_id = format(run_span.get_span_context().trace_id, "032x")
        started_at = datetime.datetime.now(datetime.UTC).isoformat()
        doc = logs = diagnosis = reply = error = None
        try:
            classify_ticket(symptom, ticket["area"])
            doc = retrieve_docs(symptom)
            logs = inspect_logs(ticket["id"], symptom)
            diagnosis = propose_diagnosis(symptom, doc, logs["lines"])
            reply = draft_reply(symptom, diagnosis)
            await_approval()
        except Exception as e:
            error = str(e)
        ended_at = datetime.datetime.now(datetime.UTC).isoformat()
        context = f"{doc or ''}\n" + "\n".join((logs or {}).get("lines", []))
        write_trace_file(trace_id, symptom, context, logs, reply)
        failed, reason = evaluate_run(trace_id, reply, error)
        insert_run(trace_id, symptom, reply, failed, reason, started_at, ended_at,
                   pipeline="triage", approval="pending_approval")
        return {"trace_id": trace_id, "ticket_id": ticket["id"], "diagnosis": diagnosis, "draft_reply": reply,
                "failed": failed, "reason": reason, "approval": "pending_approval"}
