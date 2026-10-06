import json
import pathlib

TRACES_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "traces"


def write_trace_file(trace_id: str, query: str, context: str | None,
                      tool_result: dict | None, answer: str | None) -> dict:
    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "trace_id": trace_id,
        "query": query,
        "context": context,
        "tool_result": tool_result,
        "answer": answer,
    }
    (TRACES_DIR / f"{trace_id}.json").write_text(json.dumps(record, indent=2, default=str))
    return record


def read_trace_file(trace_id: str) -> dict | None:
    path = TRACES_DIR / f"{trace_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
