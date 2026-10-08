"""Phase 12. Usage:
  eval_triage.py run     run every ticket x fault, save data/triage_eval.json
  eval_triage.py score   hand-score diagnoses vs the golden root cause
  eval_triage.py recheck re-run the current detector on stored traces (keeps scores)
  eval_triage.py report  table: did the detector catch each fault?
"""
import collections
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS = ROOT / "data" / "triage_eval.json"
GOLDEN = json.loads((ROOT / "data" / "golden" / "triage_golden.json").read_text())
FAULTS = ["baseline", "remove_logs", "wrong_doc", "tool_throws", "truncate_reply", "fabricate_evidence"]


def load():
    return json.loads(RESULTS.read_text()) if RESULTS.exists() else {}


def save(d):
    RESULTS.write_text(json.dumps(d, indent=2))


def run():
    from app.pipeline.triage import run_triage
    d = load()
    for tid in GOLDEN:
        for f in FAULTS:
            os.environ.pop("TRIAGE_FAULT", None)
            if f != "baseline":
                os.environ["TRIAGE_FAULT"] = f
            r = run_triage(tid)
            d[f"{tid}|{f}"] = {"ticket": tid, "fault": f, "trace_id": r["trace_id"], "failed": r["failed"],
                               "reason": r["reason"], "diagnosis": r["diagnosis"], "reply": r["draft_reply"]}
            print(tid, f, "FLAGGED" if r["failed"] else "passed", (r["reason"] or "")[:70])
    os.environ.pop("TRIAGE_FAULT", None)
    save(d)


def score():
    d = load()
    for k, v in d.items():
        if "score" in v:
            continue
        print(f"\n[{k}] TRUE: {GOLDEN[v['ticket']]['root_cause']}")
        print("DIAGNOSIS:", json.dumps(v["diagnosis"]))
        print("REPLY:", (v["reply"] or "")[:400])
        c = input("[c]orrect / [p]artial / [i]ncorrect / [s]kip / [q]uit: ").strip().lower()
        if c == "q":
            break
        if c in ("c", "p", "i"):
            v["score"] = {"c": "correct", "p": "partial", "i": "incorrect"}[c]
            save(d)


def recheck():
    from app.tracing.evaluate import evaluate_run
    d = load()
    for k, v in d.items():
        failed, reason = evaluate_run(v["trace_id"], v["reply"], None)
        if failed != v["failed"] or reason != v["reason"]:
            print(f"{k}: {v['failed']} -> {failed} {reason}")
        v["failed"], v["reason"] = failed, reason
    save(d)


def report():
    d = load()
    print(f"{'fault':20} {'n':>2} {'flagged':>7} {'wrong':>5} {'wrong&missed':>12}  reasons")
    for f in FAULTS:
        rs = [v for v in d.values() if v["fault"] == f]
        if not rs:
            continue
        scored = [v for v in rs if "score" in v]
        wrong = [v for v in scored if v["score"] != "correct"]
        missed = [v for v in wrong if not v["failed"]]
        reasons = collections.Counter((v["reason"] or "-").split(":")[0] for v in rs if v["failed"])
        print(f"{f:20} {len(rs):>2} {sum(v['failed'] for v in rs):>7} {len(wrong):>5} {len(missed):>12}  {dict(reasons)}"
              + ("" if len(scored) == len(rs) else f"  ({len(rs) - len(scored)} unscored)"))


if __name__ == "__main__":
    {"run": run, "score": score, "recheck": recheck, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
