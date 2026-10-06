import json
import pathlib
import sqlite3

DB_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "forensics.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  trace_id TEXT PRIMARY KEY,
  started_at TEXT,
  ended_at TEXT,
  input TEXT,
  output TEXT,
  status TEXT,              -- 'ok' | 'failed'
  fail_reason TEXT,
  flagged INTEGER DEFAULT 0,
  flag_reason TEXT
);

CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT REFERENCES runs(trace_id),
  parent_span_id TEXT,
  name TEXT,
  started_at INTEGER,
  ended_at INTEGER,
  status TEXT,
  latency_ms REAL,
  attributes TEXT            -- JSON blob
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def insert_span(span: dict) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO spans "
        "(span_id, trace_id, parent_span_id, name, started_at, ended_at, status, latency_ms, attributes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            span["span_id"],
            span["trace_id"],
            span["parent_span_id"],
            span["name"],
            span["started_at"],
            span["ended_at"],
            span["status"],
            span["latency_ms"],
            json.dumps(span["attributes"], default=str),
        ),
    )
    conn.commit()
    conn.close()


def insert_run(trace_id: str, query: str, answer: str | None, failed: bool,
                reason: str | None, started_at: str, ended_at: str) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO runs (trace_id, started_at, ended_at, input, output, status, fail_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trace_id, started_at, ended_at, query, answer, "failed" if failed else "ok", reason),
    )
    conn.commit()
    conn.close()


def list_runs(status: str | None = None) -> list[dict]:
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM runs WHERE status = ? ORDER BY started_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_run_with_spans(trace_id: str) -> dict | None:
    conn = get_conn()
    run = conn.execute("SELECT * FROM runs WHERE trace_id = ?", (trace_id,)).fetchone()
    if run is None:
        conn.close()
        return None
    spans = conn.execute(
        "SELECT * FROM spans WHERE trace_id = ? ORDER BY started_at", (trace_id,)
    ).fetchall()
    conn.close()
    result = dict(run)
    result["spans"] = [
        {**dict(s), "attributes": json.loads(s["attributes"]) if s["attributes"] else {}}
        for s in spans
    ]
    return result


def set_flagged(trace_id: str, flagged: bool, reason: str | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE runs SET flagged = ?, flag_reason = ? WHERE trace_id = ?",
        (1 if flagged else 0, reason, trace_id),
    )
    conn.commit()
    conn.close()


def max_step_latency(trace_id: str) -> float:
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(latency_ms) AS m FROM spans WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    conn.close()
    return row["m"] or 0.0


def export_flagged_jsonl() -> str:
    from app.storage.traces import read_trace_file

    conn = get_conn()
    rows = conn.execute("SELECT * FROM runs WHERE flagged = 1 ORDER BY started_at").fetchall()
    conn.close()
    lines = []
    for r in rows:
        record = dict(r)
        record["trace"] = read_trace_file(record["trace_id"])
        lines.append(json.dumps(record, default=str))
    return "\n".join(lines)
