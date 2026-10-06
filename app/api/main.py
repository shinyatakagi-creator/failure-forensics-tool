from fastapi import FastAPI, HTTPException, Response

from app.pipeline.run import run_pipeline
from app.storage import db

app = FastAPI(title="Failure Forensics API")


@app.post("/runs")
def create_run(body: dict):
    return run_pipeline(body["query"])


@app.get("/runs")
def list_runs(status: str | None = None):
    return db.list_runs(status=status)


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


@app.get("/eval-dataset")
def export_eval_dataset():
    return Response(content=db.export_flagged_jsonl(), media_type="application/x-ndjson")
