# Failure Forensics Tool

Traces a small RAG + calculator pipeline with OpenTelemetry spans (SQLite), flags failed runs, and exports flagged runs as an eval dataset. Personal project; all data is synthetic.

## Detector

Checks, in order: tool error/empty (`tool.status` span attribute), exception, empty/short answer, step latency, groundedness judge.

- **Judge model:** `gpt-4o` (`JUDGE_MODEL`), generator is `gpt-4o-mini` (`GEN_MODEL`). Same provider and family, different size. This reduces but does not remove shared blind spots.
- **Groundedness:** the judge sees retrieved context and the tool result; an answer derived from the tool result counts as grounded. Score and one-line reason are stored on the `judge_groundedness` span.

## Measured accuracy

Hand-labelled with `scripts/label_runs.py`, scored with `scripts/eval_detector.py`.

| | pred failed | pred ok |
|---|---|---|
| **true failed** | 7 | 0 |
| **true ok** | 2 | 35 |

n=44, precision 0.78, recall 1.00.

Limits:
- Only 7 true failures, all exceptions, empty input or tool errors. Recall of 1.00 says nothing about subtle failures (wrong-but-fluent answers, bad retrieval); this set has none.
- The 2 false positives are both groundedness-judge errors on correct answers: `100 / 4` scored 1/5 (an older run, before the tool-result fix) and a new-hire vacation answer scored 2/5 whose stated reason is weak (post-fix, so the judge still errs).
- The first 12 runs predate the detector fix, so the metrics mix the old and new detector.
- Labels were corrected once after an `f`/`o` mix-up during labelling.

## Run

```
.venv/bin/python scripts/seed_failures.py 40   # generate runs
.venv/bin/python scripts/label_runs.py         # hand-label
.venv/bin/python scripts/eval_detector.py      # precision / recall
```

## Triage agent (synthetic)

`POST /tickets/{id}/triage` runs a support-escalation agent over synthetic tickets and logs (`data/tickets`, `data/logs`; 4 tickets so far). Steps: classify, retrieve doc, grep logs (the model picks the regex), diagnose with cited log lines, draft reply. Nothing is ever sent: every run stores `approval=pending_approval` until `POST /runs/{id}/approve` or `/reject`. Emails/IPs are redacted before model calls; `TRIAGE_KILL_SWITCH` disables the agent. This is a personal project, not a production deployment.

## Fault injection (4 tickets x 6 conditions, hand-scored diagnoses)

`scripts/eval_triage.py run|score|recheck|report`. "wrong" = diagnosis scored partial/incorrect (an empty diagnosis counts as incorrect). Detector after adding the evidence-in-logs check:

| Fault | flagged /4 | wrong /4 | wrong & not flagged | caught by |
|---|---|---|---|---|
| baseline (no fault) | 1 | 0 | 0 | judge false positive on T-001 |
| remove_logs | 4 | 4 | 0 | tool-empty check |
| tool_throws | 4 | 3 | 0 | tool-error check |
| truncate_reply | 3 | 4 | 1 | groundedness judge only |
| fabricate_evidence | 4 | 4 | 0 | evidence-in-logs check |
| wrong_doc | 0 | 2 | 2 | **nothing** |

Findings:
- Before the evidence check, `fabricate_evidence` was caught 1/4 (that one was a baseline false positive, so about 0/3 real). The new check caught 4/4, but I wrote the check after seeing that fault, so this number is tuned to the fault and says little about other fabrication styles.
- `wrong_doc` is a known blind spot: 2 of 4 diagnoses were wrong and unflagged.
- The groundedness judge is noisy. On the same stored runs, `truncate_reply` was flagged 4/4, then 2/4, then 3/4 across three judge rolls. T-001 baseline is a repeatable judge false positive. Do not treat judge results as deterministic.
- n=4 per condition: a smoke test, not a rate. Scores are one person's hand judgment, with the rubric tightened partway (abstentions count as wrong). Before/after data is in `data/triage_eval_before.json` and `data/triage_eval.json`.
- Tool-error and evidence checks rely on structure (span attributes, exact string match); only the judge relies on the model.
