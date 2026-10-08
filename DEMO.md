# Two-minute demo script

Story in one line: a ticket comes in, the agent triages it, an injected fault shows up as a failed run, I open the trace, flag it, and it lands in the eval export.

Every command here was run end to end before writing this. Rehearse once, then record.

## Before recording (not on camera)

1. **Stop any old server.** A stale API from before the triage routes were added answers "Not Found".
   ```bash
   lsof -nP -iTCP:8000 -iTCP:8001 -iTCP:8501 -sTCP:LISTEN
   kill <PID>        # for each one listed
   ```
2. **Empty the eval export** so the final step is visible. One old run (`db22e62b`, "demo flag") is flagged from the first seed:
   ```bash
   .venv/bin/python -c "from app.storage import db; [db.set_flagged(r['trace_id'], False, None) for r in db.list_runs() if r['flagged']]"
   ```
3. **Check the key** works (`.venv/bin/python -c "from app.pipeline import llm; print(llm.complete('say ok'))"`). Keep `.env` out of every shot.
4. **Layout:** three terminal tabs (A, B, C) and a browser window, font size large enough to read on a recording. Screen record with Cmd+Shift+5.

Start the servers in tabs A and B before you press record:

```bash
# Tab A: normal API
.venv/bin/uvicorn app.api.main:app --port 8000
# Tab B: the same API with a fault injected (fabricated evidence)
TRIAGE_FAULT=fabricate_evidence .venv/bin/uvicorn app.api.main:app --port 8001
# Tab C: dashboard (open http://localhost:8501, set sidebar Pipeline = triage)
.venv/bin/streamlit run app/dashboard/app.py
```

## The script (about 2:00)

| Time | On screen | Say |
|---|---|---|
| 0:00 | Terminal C. Dashboard in the browser, sidebar set to **triage**. | "This is a support triage agent over synthetic tickets, with a monitor watching every run. The point of the project is knowing which failures the monitor catches." |
| 0:15 | Tab C. Send a ticket to the normal API. | "A ticket comes in: nobody on the customer's team can log in with SSO." |
| | `curl -s -X POST localhost:8000/tickets/T-003/triage` | |
| 0:30 | Point at the JSON: `failed: false`, the diagnosis ("signing certificate has expired"), `approval: pending_approval`. | "The agent searched the logs, proposed a cause, and drafted a reply. It is pending approval. Nothing is ever sent without a person." |
| 0:45 | Same ticket, **same agent, with a fault injected**. | "Now the same ticket, but the agent invents its evidence. This is one of five faults I injected." |
| | `curl -s -X POST localhost:8001/tickets/T-003/triage` | |
| 1:00 | Point at `failed: true` and `reason: evidence not in logs: 2023-10-23 ... ERROR upstream dependency returned 500`. | "The diagnosis cites a log line the log tool never returned. The monitor fails the run and says why. The diagnosis text looks fine; you would not see this by reading it." |
| 1:15 | Browser: refresh the dashboard, newest run first (red or `failed`). Open the `propose_diagnosis` span's **details**. | "Here is the trace. The span shows the fabricated evidence next to the real log lines from the `inspect_logs` span." |
| 1:35 | Click **Flag for eval dataset**. | "I flag it so it becomes a regression case." |
| 1:45 | Tab C: `curl -s localhost:8000/eval-dataset \| head -c 600` | "And it appears in the eval export with the full trace." |
| 1:55 | Cut to `WRITEUP.md` results table (or say it): wrong-doc fault, 6 of 9 wrong diagnoses missed. | "The most useful result is what it misses: when the agent is given the wrong doc, the monitor misses 6 of 9 wrong diagnoses. That is what I would build next." |
| 2:00 | End. | |

If you run over, drop the 0:45 section's explanation of "five faults" and the final results table shot. Keep the fabricated-evidence flow, which is the core.

## Do not

- Show the `.env` file or paste the API key anywhere.
- Say "production" or "customer deployment". Say "synthetic tickets, personal project".
- Claim the monitor catches everything. The last line of the script is the honest limit.

## If something goes wrong on take two

- `{"detail":"Not Found"}` from a `curl`: the old server is still on that port. Re-run the `lsof` check.
- Every run is flagged `exception: ... 401`: the API key in `.env` is invalid or expired.
- The dashboard shows an old run first: refresh and confirm the sidebar Pipeline filter is **triage**.
- The fault run passes (`failed: false`): tab B was started without `TRIAGE_FAULT=fabricate_evidence`. The fault is read from the server's environment, so restart tab B.
