from fastapi import FastAPI, HTTPException, Response

from app.guardrails import KillSwitchOn
from app.pipeline.run import run_pipeline
from app.pipeline.triage import run_triage
from app.storage import db

app = FastAPI(title="Failure Forensics API")


@app.post("/runs")
def create_run(body: dict):
    return run_pipeline(body["query"])


@app.get("/runs")
def list_runs(status: str | None = None, pipeline: str | None = None):
    return db.list_runs(status=status, pipeline=pipeline)


@app.get("/runs/{trace_id}")
def get_run(trace_id: str):
    run = db.get_run_with_spans(trace_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.post("/runs/{trace_id}/flag")
def flag_run(trace_id: str, body: dict):
    db.set_flagged(trace_id, body["flagged"], body.get("reason"))
    return {"ok": True}


@app.post("/tickets/{ticket_id}/triage")
def triage_ticket(ticket_id: str):
    try:
        return run_triage(ticket_id)
    except KillSwitchOn:
        raise HTTPException(status_code=503, detail="triage disabled by kill switch")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="ticket not found")


def _decide(trace_id: str, approval: str, body: dict):
    if not db.set_approval(trace_id, approval, body.get("reply")):
        raise HTTPException(status_code=409, detail="run not found or not pending approval")
    return {"ok": True, "approval": approval}


@app.post("/runs/{trace_id}/approve")
def approve_run(trace_id: str, body: dict | None = None):
    return _decide(trace_id, "approved", body or {})


@app.post("/runs/{trace_id}/reject")
def reject_run(trace_id: str, body: dict | None = None):
    return _decide(trace_id, "rejected", body or {})


@app.get("/eval-dataset")
def export_eval_dataset():
    return Response(content=db.export_flagged_jsonl(), media_type="application/x-ndjson")
