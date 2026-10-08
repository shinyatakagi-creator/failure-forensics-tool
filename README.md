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

## Fault injection (20 tickets x 6 conditions = 120 runs)

`scripts/eval_triage.py run|keyscore|agreement|report --key`. Diagnoses are scored by a deterministic keyword scorer (`keyscore`, keyword groups per ticket in `triage_golden.json`): correct = the top candidate matches every keyword group and all cited evidence lines are real log lines; partial = some groups hit, or the cause hits but evidence is unverified; incorrect = no hit, no candidate, or any cited evidence not in the logs. "wrong" = partial or incorrect.

| Fault | flagged /20 | wrong /20 | wrong & not flagged | caught by |
|---|---|---|---|---|
| baseline (no fault) | 1 | 3 | 3 | judge false positive on T-001; the 3 wrong ones (T-002, T-006, T-009) are unflagged |
| remove_logs | 13 | 12 | 0 | tool-empty check (12) + judge (1) |
| tool_throws | 20 | 20 | 0 | tool-error check |
| fabricate_evidence | 20 | 20 | 0 | evidence-in-logs check |
| wrong_doc | 4 | 9 | **6** | judge only, rarely |
| truncate_reply | 8 | 5 | 3 | groundedness judge only |

Findings:
- Clean baseline: 17/20 correct, 3 partial (each missed one part of the cause, e.g. the shared API key on T-002) and none of the 3 was flagged.
- `wrong_doc` is the weakest spot: 6 wrong diagnoses with no flag.
- `truncate_reply` is caught by the groundedness judge in 8/20 runs. Keyword scoring ignores the reply, so its "wrong" column does not measure reply quality.
- `tool_throws` and `fabricate_evidence` are wrong by construction (no logs / invented evidence). Their catches come from structural checks, not the model. The evidence check was written after seeing that fault, so 20/20 is tuned to it and says little about other fabrication styles.
- `remove_logs` was flagged 13/20 but 12 diagnoses were wrong; an unflagged wrong case would show up in the last column and none did.
- The groundedness judge is noisy: on the same stored runs `truncate_reply` flagged 4/4, 2/4, then 3/4 across judge rolls (4-ticket run). T-001 baseline is a repeatable judge false positive.

Scoring validity: keyword scoring agrees with my hand scores on 14/24 rows exactly and 18/24 on correct-vs-not (n=24, first 4 tickets). An LLM scorer was tried first and agreed on only 11/24 exactly and 17/24 on correct-vs-not, so it is not used for results. Known disagreements: reply truncation is invisible to keyword scoring, and cause-from-docs-with-unverified-evidence is scored incorrect where I hand-scored partial. Hand scores for tickets 5-20 were lost to a file-overwrite bug (fixed), so those rows are keyword-scored only. Keyword lists were written by me before seeing the 16 new tickets' results, but the 4 original keyword lists were written after seeing their runs. Single run per cell, no repeats, no confidence intervals. Data: `data/triage_eval.json`, earlier 4-ticket snapshot in `data/triage_eval_before.json`.
