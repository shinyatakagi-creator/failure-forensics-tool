import re

from app.pipeline import llm
from app.pipeline.docs import search_docs
from app.tracing.tracer import tracer

_CALC_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)")


def receive_question(query: str) -> str:
    with tracer.start_as_current_span("receive_question") as span:
        span.set_attribute("input", query)
        return query


def retrieve_context(query: str) -> str:
    with tracer.start_as_current_span("retrieve_context") as span:
        span.set_attribute("input", query)
        result = search_docs(query)
        span.set_attribute("output_preview", result[:300])
        return result


def call_tool(query: str, context: str) -> dict | None:
    with tracer.start_as_current_span("call_tool") as span:
        span.set_attribute("input", query)
        match = _CALC_RE.search(query)
        if not match:
            span.set_attribute("output_preview", "no tool needed")
            return None
        a, op, b = match.groups()
        a, b = float(a), float(b)
        result = {"+": a + b, "-": a - b, "*": a * b, "/": a / b}[op]
        span.set_attribute("output_preview", str(result))
        return {"tool": "calculator", "result": result}


def generate_answer(query: str, context: str, tool_result: dict | None) -> str:
    with tracer.start_as_current_span("generate_answer") as span:
        span.set_attribute("input", query)
        if not query.strip():
            span.set_attribute("output_preview", "")
            return ""
        prompt = f"Question: {query}\nContext: {context}\nTool result: {tool_result}"
        answer = llm.complete(prompt, system="Answer using only the provided context and tool result.")
        span.set_attribute("output_preview", answer[:300])
        return answer
