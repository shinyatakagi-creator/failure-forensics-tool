# Failure Forensics Tool — Build Guide

An observability layer for multi-step AI pipelines: trace every step, pinpoint where a bad output originated, and feed flagged failures into a growing eval dataset.

This guide assumes solo development on one machine, so it skips anything that needs a cluster or a hosted backend (no Jaeger/Tempo server, no managed vector DB). Everything runs locally with SQLite and flat files, and Docker is used only to package what you already built, not to add new infrastructure.

## What "done" looks like

- A demo pipeline (Query → Retrieve → Tool → Answer) instrumented with real OpenTelemetry spans
- Every run persisted with full step-by-step timing, inputs, and outputs
- An automatic pass that decides whether a run failed, and why
- A REST API to list runs, inspect a trace, and manually flag/unflag a run
- A dashboard showing the trace timeline per run (this is what image 2's mockup is showing)
- An eval dataset that grows as failures get flagged, exportable as JSONL
- Docker Compose to run the whole thing with one command

## Repo layout

```
failure-forensics/
├── app/
│   ├── pipeline/
│   │   ├── steps.py          # the 4 pipeline steps
│   │   └── run.py            # orchestrates one end-to-end run
│   ├── tracing/
│   │   ├── tracer.py         # OTel setup + custom SpanProcessor
│   │   └── evaluate.py       # failure detection logic
│   ├── storage/
│   │   ├── db.py             # SQLite schema + helpers
│   │   └── traces.py         # JSON trace file read/write
│   ├── api/
│   │   └── main.py           # FastAPI app
│   └── dashboard/
│       └── app.py            # Streamlit dashboard
├── data/
│   ├── docs/                 # small local knowledge base for "retrieve"
│   ├── forensics.db          # SQLite (gitignored, seeded on first run)
│   └── traces/                # one JSON file per run (gitignored)
├── scripts/
│   └── seed_failures.py      # generates runs, some intentionally broken
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Phase 0: setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn opentelemetry-sdk opentelemetry-api \
    openai streamlit numpy python-dotenv
```

Put `OPENAI_API_KEY` in a `.env` file. Keep the local doc corpus in `data/docs/` to a handful of markdown files — 5-10 short docs is enough to make retrieval meaningful without needing a real vector store.

## Phase 1: instrumentation layer

Use real OpenTelemetry rather than hand-rolling a span format. It's the part of the spec that signals "industry-standard observability" to anyone reviewing the repo, and the API is small enough that it doesn't cost you much time.

The trick for a solo project: skip standing up a collector backend. Write a custom `SpanProcessor` that, on span end, persists straight into SQLite. You get proper OTel semantics (trace ID, span ID, parent/child, status, attributes) without running Jaeger.

```python
# app/tracing/tracer.py
import time, json
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
            "attributes": dict(span.attributes),
            "latency_ms": (span.end_time - span.start_time) / 1e6,
        })

provider = TracerProvider()
provider.add_span_processor(SQLiteSpanProcessor())
# optional, useful while developing:
provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("failure-forensics")
```

Each pipeline step becomes:

```python
# app/pipeline/steps.py
from app.tracing.tracer import tracer

def retrieve_context(query: str) -> str:
    with tracer.start_as_current_span("retrieve_context") as span:
        span.set_attribute("input", query)
        result = _search_docs(query)          # your retrieval logic
        span.set_attribute("output_preview", result[:300])
        return result
```

Wrap each of the four steps (`receive_question`, `retrieve_context`, `call_tool`, `generate_answer`) the same way. Exceptions inside the `with` block are captured by OTel automatically and mark the span as errored — you don't need to catch them yourself for tracing purposes, just let them propagate and record status downstream.

## Phase 2: storage

Two layers, matching the spec:

**SQLite** — structured, queryable, what the dashboard and API read from.

```sql
CREATE TABLE runs (
  trace_id TEXT PRIMARY KEY,
  started_at TEXT,
  ended_at TEXT,
  input TEXT,
  output TEXT,
  status TEXT,              -- 'ok' | 'failed'
  fail_reason TEXT,
  flagged INTEGER DEFAULT 0
);

CREATE TABLE spans (
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
```

**JSON trace files** (`data/traces/{trace_id}.json`) — the full, untruncated record of one run: complete inputs/outputs at every step. SQLite stores previews for the dashboard; these files are what you export into the eval dataset later, since you don't want to lose detail to truncation.

## Phase 3: the demo pipeline

Keep it simple enough to build in a day, complex enough to fail in interesting ways:

1. **receive_question** — just logs the raw input
2. **retrieve_context** — embed the query with OpenAI embeddings, cosine-similarity against pre-embedded chunks from `data/docs/`, return the top match. No vector DB needed at this corpus size — `numpy` and a dict is fine.
3. **call_tool** — one simple tool, e.g. a calculator or a stub "search" function invoked via OpenAI function calling. This is the step most likely to fail (bad args, tool returns nothing) which makes it useful for the forensics story.
4. **generate_answer** — final completion using the retrieved context and tool result.

```python
# app/pipeline/run.py
from app.tracing.tracer import tracer
from app.pipeline import steps
from app.tracing.evaluate import evaluate_run
from app.storage.db import insert_run
from app.storage.traces import write_trace_file

def run_pipeline(query: str) -> dict:
    with tracer.start_as_current_span("run") as run_span:
        trace_id = format(run_span.get_span_context().trace_id, "032x")
        try:
            steps.receive_question(query)
            context = steps.retrieve_context(query)
            tool_result = steps.call_tool(query, context)
            answer = steps.generate_answer(query, context, tool_result)
        except Exception as e:
            answer = None
            error = str(e)
        else:
            error = None

        failed, reason = evaluate_run(trace_id, answer, error)
        insert_run(trace_id, query, answer, failed, reason)
        write_trace_file(trace_id, query, context, tool_result, answer)
        return {"trace_id": trace_id, "output": answer, "failed": failed, "reason": reason}
```

## Phase 4: failure detection

This is the part that makes the tool worth having. A run counts as failed if any of these trip:

- an exception propagated out of any step
- the final answer is empty, None, or under some length threshold
- any step's latency exceeded a threshold (e.g. 8s) — surfaces silent slowness, not just hard errors
- the tool call returned an error or null result
- an LLM-as-judge check: a cheap secondary call scores the answer for groundedness against the retrieved context (1-5), flagged if it scores low

```python
# app/tracing/evaluate.py
def evaluate_run(trace_id: str, answer: str | None, error: str | None) -> tuple[bool, str | None]:
    if error:
        return True, f"exception: {error}"
    if not answer or len(answer.strip()) < 10:
        return True, "empty or degenerate output"
    if _max_step_latency(trace_id) > 8000:
        return True, "step latency exceeded threshold"
    score = _judge_groundedness(trace_id, answer)
    if score < 3:
        return True, f"low groundedness score ({score}/5)"
    return False, None
```

The judge call is optional for v1 — it's the piece that reads as "sophisticated" in an interview, but the first three checks alone already demonstrate the core idea. Build those first.

## Phase 5: REST API (the feedback loop)

FastAPI, four endpoints:

- `POST /runs` — body `{"query": "..."}`, executes the pipeline synchronously, returns the result
- `GET /runs?status=failed` — list runs, filterable
- `GET /runs/{trace_id}` — full trace: run record + ordered spans
- `POST /runs/{trace_id}/flag` — body `{"flagged": true, "reason": "..."}`, human override on top of the automatic evaluation
- `GET /eval-dataset` — every flagged run, JSONL, one object per line — this is the "growing evaluation dataset" from the spec

```python
# app/api/main.py
from fastapi import FastAPI
from app.pipeline.run import run_pipeline
from app.storage import db

app = FastAPI()

@app.post("/runs")
def create_run(body: dict):
    return run_pipeline(body["query"])

@app.get("/runs")
def list_runs(status: str | None = None):
    return db.list_runs(status=status)

@app.get("/runs/{trace_id}")
def get_run(trace_id: str):
    return db.get_run_with_spans(trace_id)

@app.post("/runs/{trace_id}/flag")
def flag_run(trace_id: str, body: dict):
    db.set_flagged(trace_id, body["flagged"], body.get("reason"))
    return {"ok": True}

@app.get("/eval-dataset")
def export_eval_dataset():
    return db.export_flagged_jsonl()
```

## Phase 6: dashboard

Given the timeline, build this in Streamlit first rather than React. It gets you a working, clickable dashboard in under a day, and Streamlit supports enough custom CSS to get reasonably close to the dark trace-timeline look in the mockup. Treat a full React rebuild as a stretch goal only if the rest is done early — it's not what makes the project land in an interview, the tracing and failure logic is.

Two views:
- **Run list** — table of recent runs, status badge (ok/failed), filter by flagged
- **Run detail** — the step list from the mockup: name, status, latency, expandable input/output, in execution order

```python
# app/dashboard/app.py
import streamlit as st
from app.storage import db

st.set_page_config(page_title="Failure Forensics", layout="wide")
runs = db.list_runs()

selected = st.selectbox("Run", [r["trace_id"] for r in runs])
run = db.get_run_with_spans(selected)

st.write(f"Status: **{run['status']}**  ·  Reason: {run.get('fail_reason') or '—'}")
for span in run["spans"]:
    icon = "✅" if span["status"] == "OK" else "⚠️"
    st.write(f"{icon} **{span['name']}** — {span['latency_ms']:.0f}ms")
    with st.expander("details"):
        st.json(span["attributes"])

if st.button("Flag for eval dataset"):
    db.set_flagged(selected, True, "manual review")
```

## Phase 7: seed the eval dataset

An empty dashboard doesn't demo well. Write a script that runs the pipeline N times, occasionally injecting a fault on purpose (skip retrieval, feed the tool malformed input, truncate the answer), so you walk into a demo with a populated, growing dataset instead of a blank table.

```python
# scripts/seed_failures.py
import random
from app.pipeline.run import run_pipeline

QUERIES = [...]  # a few dozen sample questions against your doc set

for q in QUERIES:
    if random.random() < 0.2:
        q = ""  # force a degenerate-output failure
    run_pipeline(q)
```

## Phase 8: Docker

Package what exists — don't add new services. One image, two processes via compose (API + dashboard), one shared volume for the SQLite file and trace directory.

```yaml
# docker-compose.yml
services:
  api:
    build: .
    command: uvicorn app.api.main:app --host 0.0.0.0 --port 8000
    ports: ["8000:8000"]
    volumes: ["./data:/app/data"]
  dashboard:
    build: .
    command: streamlit run app/dashboard/app.py --server.port 8501 --server.address 0.0.0.0
    ports: ["8501:8501"]
    volumes: ["./data:/app/data"]
```

## Phase 9: portfolio polish

- README with the architecture diagram (Query → Retrieve → Tool → Answer, tracer sitting alongside), and a short "why this matters" paragraph — this is a mini LangSmith/Braintrust, and most teams genuinely have no way to answer "where did this go wrong" today
- A short screen recording: trigger a run, watch it show up as failed, click into the trace, flag it, show it land in the eval dataset export
- Push with normal incremental commits rather than one big commit — it reads as an actual build process rather than a dump

## Suggested build order

Phases 0-4 (tracer, storage, pipeline, failure detection) are the core of the idea and worth getting solid first — that's what you'd actually talk through in an interview. Phases 5-6 (API, dashboard) turn it into something demoable. Docker and polish come last and shouldn't take long once the rest works.
