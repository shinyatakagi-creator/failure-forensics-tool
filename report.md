# Failure Forensics Tool — Report

## Seeded run results

`scripts/seed_failures.py` (10 base queries, deterministic `random.seed(0)`, fault substitution ~20% of the time) produced:

- **12 runs total**
- **8 ok**, **4 failed** (33% failure rate)
- **1 of the 12** additionally flagged for the eval dataset (`flag_reason: "demo flag"`) — flagging is independent of pass/fail status

| Cause | Count | Trigger |
|---|---|---|
| Low groundedness score (1/5) | 2 | Correctly-computed arithmetic answers scored ungrounded against an unrelated retrieved policy doc |
| Exception: float division by zero | 2 | `"What is 10 / 0?"` → unhandled `ZeroDivisionError` in the calculator tool |

Verified `OPENAI_API_KEY` was set for this run: none of the 12 stored answers in `data/traces/` match the offline fallback template (`"Based on the available context: ..."`), so generation used real `gpt-4o-mini` calls, and — since `HAS_API_KEY` gates both paths — the groundedness scoring did too, not the word-overlap heuristic. The two 1/5 scores are real `gpt-4o-mini` judge output, not a heuristic approximation.

This is a fixed fixture over 10 hardcoded queries, not a live-traffic sample — useful for exercising both failure paths reproducibly, not for measuring a real-world failure rate.

## Failure checks (`app/tracing/evaluate.py`)

| Check | Implemented? | Detail |
|---|---|---|
| Exception | ✅ | `if error: return True, f"exception: {error}"` |
| Empty or short answer | ✅ | `len(answer.strip()) < MIN_ANSWER_LEN` (10 chars) |
| Slow step (latency threshold) | ✅ | `max_step_latency(trace_id) > LATENCY_THRESHOLD_MS` (8000ms) |
| Tool error or null result | ❌ | Not a distinct check. `call_tool` returning `None` (no tool needed) is normal; a tool exception isn't caught separately, it propagates up and is reported as a generic `"exception: ..."` |
| Groundedness judge | ✅ | `_judge_groundedness`, threshold `MIN_GROUNDEDNESS = 3` |

4 of the 5 common checks exist as distinct checks; tool error/null result is only incidentally covered via the generic exception path.

## Judge

A second LLM call via `llm.complete()`, `system="You are a strict grading judge."` — prompt feeds retrieved context + answer, asks for a 1–5 digit score.

- Model: **`gpt-4o-mini`** — same model used for the main answer generation, not a separate/stronger judge model.
- Code has a no-key fallback (word-overlap heuristic), but the seeded run did not use it — see confirmation above. Call it a groundedness score from a real judge call, not an approximation.

## Pipeline

- **Retrieval**: OpenAI embeddings (`text-embedding-3-small`) over 6 markdown docs in `data/docs/` (vacation, expense, onboarding, security, remote-work, support-contacts policies). Cosine similarity picks the single best-matching **whole document** — no chunking, no top-k.
- **Tool**: regex-based calculator (`_CALC_RE` matches `a op b`, handles `+ - * /`). The seeded `10 / 0` query hits this and raises `ZeroDivisionError`.
- Both retrieval and generation have no-API-key fallbacks (hash-based bag-of-words embedding, templated string answer), so the pipeline runs deterministically offline too.

## Dashboard

**Streamlit** (`app/dashboard/app.py`). Single page: dropdown to pick a run, shows status/fail_reason/flagged, lists each span with latency and an expander for raw attributes JSON, and a "Flag for eval dataset" button.

## API

**FastAPI** (`app/api/main.py`):

- `POST /runs` — execute the pipeline for a query
- `GET /runs` — list runs, optional `?status=` filter
- `GET /runs/{trace_id}` — inspect a trace (run + its spans)
- `POST /runs/{trace_id}/flag` — flag/unflag with a reason
- `GET /eval-dataset` — export all flagged runs as JSONL (NDJSON), each record including the full trace file

## Resume project slot

Five projects won't fit a two-page resume. Keeping the RAG tool and the regression gate; this forensics tool should replace the **semantic cache** project rather than the **cost routing** project — semantic caching is a well-known, commodity pattern with a less differentiating story, while cost routing demonstrates a decision layer (cost/latency/quality tradeoffs) that pairs better thematically with the regression gate and this tool: together they read as "builds the eval/observability layer around LLM systems," with cost routing adding the one cost/latency angle otherwise missing. This is a strategic call, not verified against the actual semantic-cache/cost-routing code.

## Repo

https://github.com/shinyatakagi-creator/failure-forensics-tool (private)
