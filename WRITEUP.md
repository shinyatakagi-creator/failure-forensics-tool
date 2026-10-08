# Failure Forensics: catching bad runs in a support-triage agent

A personal project. All tickets, logs and docs are synthetic and nothing here is a production or customer deployment.

## The problem

A support team wants an agent that reads an escalated ticket, searches the logs, proposes a root cause and drafts a reply. The risk is not that the agent is sometimes wrong. The risk is that nobody can tell when. A fluent, confident draft built on missing or invented evidence looks the same as a good one, and a human reviewer under time pressure will approve it.

So the question I set out to answer was not "is the agent accurate" but "which failures would the monitoring catch, and which would it miss".

## Constraints

- A human approves every reply. The agent never sends anything.
- Customer text can contain emails and IP addresses, so those are redacted before any model call.
- A kill switch (`TRIAGE_KILL_SWITCH`) stops the agent.
- Small budget: one provider (OpenAI), one person labelling, tens of runs, not thousands.

## What I built

1. **Tracing.** Every pipeline step is an OpenTelemetry span stored in SQLite, with a FastAPI API and a Streamlit dashboard. Failed runs can be flagged and exported as an eval dataset.
2. **A failure detector** that runs after each run: tool error or empty tool result, exception, empty answer, step latency, a check that every log line the diagnosis cites was actually returned by the log tool, and an LLM groundedness judge.
3. **A triage agent** over 20 synthetic tickets: classify, retrieve a doc, grep the ticket's logs (the model picks the regex), propose a diagnosis with cited log lines, draft a reply, wait for approval.
4. **Measurement.** The detector was scored against my hand labels, then the whole agent was run under five injected faults to see what gets caught.

## Decisions and why

- **Separate judge model.** The judge is `gpt-4o`; the generator is `gpt-4o-mini`. Same provider and family, so this reduces but does not remove shared blind spots. I would use a different model family if I had a second provider key.
- **Tool checks are structural, not model-based.** The log tool records `tool.status` (ok, empty, error) on its span, and the detector reads it. This catches a broken or empty tool every time and cannot be fooled by fluent output.
- **Evidence must exist.** My first real run showed the model inventing log lines when its search returned nothing. I added a check that fails any diagnosis citing a line the tool did not return. I wrote that check after seeing the failure, so its result is tuned to that case (see limits).
- **Scoring diagnoses.** I first tried an LLM scorer against the known root causes. It agreed with my hand scores on only 11 of 24 rows, so I did not use it. A deterministic keyword scorer agreed on 14 of 24 exactly (18 of 24 on correct vs not), and I report results with that, with its disagreements listed.

## Results

**Detector on the demo pipeline** (44 hand-labelled runs, 7 real failures): precision 0.78, recall 1.00. The 2 false positives were both groundedness-judge errors on correct answers. Only 7 failures, all of simple kinds (exceptions, empty input, tool crash), so recall of 1.00 says nothing about subtle failures.

**Triage agent, clean runs (20 tickets):** 17 diagnoses correct, 3 partial (each missed part of the cause, for example a shared API key). None of the 3 was flagged. 1 of 20 clean runs was flagged by the judge, which was a false positive.

**Under injected faults (20 tickets each):**

| Fault | Flagged | Diagnosis wrong | Wrong and not flagged | Caught by |
|---|---|---|---|---|
| remove the relevant log lines | 13 | 12 | 0 | empty-tool check |
| log tool throws | 20 | 20 | 0 | tool-error check |
| fabricated evidence | 20 | 20 | 0 | evidence-in-logs check |
| wrong reference doc | 4 | 9 | **6** | judge, rarely |
| truncated reply | 8 | not measured | n/a | judge only |

The useful finding is the wrong-doc row. When the agent is handed an irrelevant doc, the diagnosis is wrong in 9 of 20 runs and the detector flags 4 of them, missing 6. Nothing in the detector compares the diagnosis to the retrieved document, and the judge only sees fluent text. The next thing I would build is a check that the diagnosis is supported by the retrieved doc or logs.

## Regression gate

To keep the detector useful as the agent changes, `eval_triage.py gate <variant>` reruns all 20 tickets three times with a changed diagnosis prompt and compares against a recorded baseline. It fails when mean correct drops, or mean flagged rises, by more than the baseline's own run-to-run spread.

| Prompt change | Mean correct | Mean flagged | Verdict |
|---|---|---|---|
| baseline (reference) | 0.75 | 0.15 | n/a |
| original prompt, before the fabrication fix | 0.77 | 0.08 | pass |
| "keep each cause under 15 words" | 0.60 | 0.15 | pass, borderline |
| "paraphrase the evidence" | 0.00 | 1.00 | **fail** |

A one-run gate was my first version, and it failed an unchanged prompt: single passes of the same prompt scored between 13 and 18 of 20. That is why the gate uses repeats and a measured tolerance (0.20 here). The cost is sensitivity: only large drops fail. The "under 15 words" change scored 12 of 20 on all three repeats, regressing the same three tickets each time, which looks like a real effect (or the keyword scorer penalising short text), and it still passed. The paraphrase change fails because every run trips the evidence-in-logs check.

## What it does not do

- The regression gate catches only large regressions (roughly 4 or more tickets of 20 on average) and uses 3 repeats of one model.
- It does not prove accuracy at scale. 20 tickets, one run per cell, no repeats and no confidence intervals. Treat the rates as a smoke test.
- The judge is noisy. On the same stored runs, truncated replies were flagged 4 of 4, then 2 of 4, then 3 of 4 across three judge calls. Judge-only catches should not be trusted individually.
- The evidence check, the keyword lists and the fault definitions were written by me after seeing similar failures. The 20 of 20 on fabricated evidence only means that check handles the fault I injected, not other forms of fabrication.
- Keyword scoring cannot see reply quality. Truncated or off-tone replies are measured only by the judge flag rate.
- Synthetic logs are cleaner than real ones. Real logs are larger, noisier and have ambiguous causes.
- My hand scores for tickets 5 to 20 were lost to a file-overwrite bug in my own eval script (fixed), so those rows are keyword-scored only.
- Not a production deployment: no auth on the API, no real data, no load testing.

## Reproduce

```
.venv/bin/python scripts/seed_failures.py 40 && .venv/bin/python scripts/label_runs.py && .venv/bin/python scripts/eval_detector.py
.venv/bin/python scripts/eval_triage.py run && .venv/bin/python scripts/eval_triage.py keyscore && .venv/bin/python scripts/eval_triage.py report --key
```
