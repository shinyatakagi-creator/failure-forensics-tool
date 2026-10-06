import datetime

from app.pipeline import steps
from app.storage.db import insert_run
from app.storage.traces import write_trace_file
from app.tracing.evaluate import evaluate_run
from app.tracing.tracer import tracer


def run_pipeline(query: str) -> dict:
    with tracer.start_as_current_span("run") as run_span:
        trace_id = format(run_span.get_span_context().trace_id, "032x")
        started_at = datetime.datetime.now(datetime.UTC).isoformat()
        context = tool_result = answer = None
        error = None
        try:
            steps.receive_question(query)
            context = steps.retrieve_context(query)
            tool_result = steps.call_tool(query, context)
            answer = steps.generate_answer(query, context, tool_result)
        except Exception as e:
            error = str(e)
        ended_at = datetime.datetime.now(datetime.UTC).isoformat()

        write_trace_file(trace_id, query, context, tool_result, answer)
        failed, reason = evaluate_run(trace_id, answer, error)
        insert_run(trace_id, query, answer, failed, reason, started_at, ended_at)
        return {"trace_id": trace_id, "output": answer, "failed": failed, "reason": reason}
