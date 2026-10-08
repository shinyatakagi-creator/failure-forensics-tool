import streamlit as st

from app.storage import db

st.set_page_config(page_title="Failure Forensics", layout="wide")

pipeline = st.sidebar.selectbox("Pipeline", ["all", "demo", "triage"])
runs = db.list_runs(pipeline=None if pipeline == "all" else pipeline)
if not runs:
    st.info("No runs yet. Run scripts/seed_failures.py first.")
    st.stop()

status_by_id = {r["trace_id"]: r["status"] for r in runs}
selected = st.selectbox(
    "Run", [r["trace_id"] for r in runs],
    format_func=lambda t: f"{t[:8]} · {status_by_id[t]}",
)
run = db.get_run_with_spans(selected)

st.write(
    f"Status: **{run['status']}**  ·  Reason: {run.get('fail_reason') or '—'}  ·  "
    f"Flagged: {'yes' if run['flagged'] else 'no'}  ·  Approval: {run.get('approval') or '—'}"
)
for span in run["spans"]:
    icon = "⚠️" if span["status"] == "ERROR" else "✅"
    st.write(f"{icon} **{span['name']}** — {span['latency_ms']:.0f}ms")
    with st.expander("details"):
        st.json(span["attributes"])

if st.button("Flag for eval dataset"):
    db.set_flagged(selected, True, "manual review")
    st.rerun()
