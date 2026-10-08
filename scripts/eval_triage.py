"""Phase 12. Usage:
  eval_triage.py run     run every ticket x fault not yet run, save data/triage_eval.json
  eval_triage.py score   hand-score diagnoses vs the golden root cause
  eval_triage.py recheck re-run the current detector on stored traces (keeps scores)
  eval_triage.py autoscore  LLM-score every row with no auto_score (separate from hand scores)
  eval_triage.py agreement  auto vs hand scores on rows you scored yourself
  eval_triage.py gate <variant> [N]  N repeats (default 3) of a prompt variant vs the recorded baseline; exit 1 on regression
  eval_triage.py keyscore   deterministic keyword score (key_score)
  eval_triage.py report     hand score if present, else key_score  table: did the detector catch each fault?
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
    tmp = RESULTS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(RESULTS)  # atomic: a reader never sees half a file


def put(key, **fields):
    """Merge fields into one row on top of the latest file, so run/score/recheck never clobber each other."""
    d = load()
    d.setdefault(key, {}).update(fields)
    save(d)


def run():
    from app.pipeline.triage import run_triage
    for tid in GOLDEN:
        for f in FAULTS:
            if f"{tid}|{f}" in load():
                continue  # resume: keep earlier results and their scores
            os.environ.pop("TRIAGE_FAULT", None)
            if f != "baseline":
                os.environ["TRIAGE_FAULT"] = f
            r = run_triage(tid)
            put(f"{tid}|{f}", ticket=tid, fault=f, trace_id=r["trace_id"], failed=r["failed"],
                reason=r["reason"], diagnosis=r["diagnosis"], reply=r["draft_reply"])
            print(tid, f, "FLAGGED" if r["failed"] else "passed", (r["reason"] or "")[:70])
    os.environ.pop("TRIAGE_FAULT", None)


def score():
    for k, v in load().items():
        if "score" in load()[k]:
            continue
        print(f"\n[{k}] TRUE: {GOLDEN[v['ticket']]['root_cause']}")
        print("DIAGNOSIS:", json.dumps(v["diagnosis"]))
        print("REPLY:", (v["reply"] or "")[:400])
        c = input("[c]orrect / [p]artial / [i]ncorrect / [s]kip / [q]uit: ").strip().lower()
        if c == "q":
            break
        if c in ("c", "p", "i"):
            put(k, score={"c": "correct", "p": "partial", "i": "incorrect"}[c])


def recheck():
    from app.tracing.evaluate import evaluate_run
    for k, v in load().items():
        failed, reason = evaluate_run(v["trace_id"], v["reply"], None)
        if failed != v["failed"] or reason != v["reason"]:
            print(f"{k}: {v['failed']} -> {failed} {reason}")
        put(k, failed=failed, reason=reason)


RUBRIC = ("You grade a support-ticket triage result against the true root cause. 'correct' = the top candidate states "
          "the true cause in substance, its evidence lines are genuine (each appears verbatim in the REAL LOG LINES), "
          "and the reply is complete. 'partial' = right area or symptom but misses the key factor, OR the cause is "
          "right but evidence is missing/unsupported by the real logs, OR the reply is cut off. 'incorrect' = unrelated, "
          "wrong, no candidate, or evidence fabricated (not in the real log lines). "
          "Reply with exactly one word: correct, partial, or incorrect.")


def autoscore():
    from app.pipeline import llm
    from app.storage.traces import read_trace_file
    redo = "--redo" in sys.argv
    for k, v in load().items():
        if "auto_score" in v and not redo:
            continue
        cands = (v["diagnosis"] or {}).get("candidates") or []
        if not cands:  # same rule as my hand scoring: an abstention is incorrect
            verdict = "incorrect"
        else:
            real = ((read_trace_file(v["trace_id"]) or {}).get("tool_result") or {}).get("lines", [])
            out = llm.complete(f"True root cause: {GOLDEN[v['ticket']]['root_cause']}\n"
                               f"Candidates (cause + evidence): {json.dumps(cands)}\n"
                               f"REAL LOG LINES returned by the tool: {json.dumps(real)}\n"
                               f"Draft reply: {v['reply']}",
                               system=RUBRIC, model=llm.JUDGE_MODEL).strip().lower()
            verdict = next((w for w in ("incorrect", "partial", "correct") if w in out), "incorrect")
        put(k, auto_score=verdict)


def key_verdict(v):
    """Deterministic score from golden keywords. correct: every keyword group hits the top candidate AND its
    evidence is verified in the real log lines. partial: some groups hit, or cause hits but evidence isn't
    verified. incorrect: no hit, no candidate, or any cited evidence line is not a real log line."""
    from app.storage.traces import read_trace_file
    cands = (v["diagnosis"] or {}).get("candidates") or []
    if not cands:
        return "incorrect"
    real = ((read_trace_file(v["trace_id"]) or {}).get("tool_result") or {}).get("lines", [])
    cause = cands[0]["cause"].lower()
    hits = [any(w in cause for w in group) for group in GOLDEN[v["ticket"]]["keywords"]]
    evidence = [e.strip() for c in cands for e in c.get("evidence", [])]
    if any(e not in real for e in evidence) or not any(hits):
        return "incorrect"
    return "correct" if all(hits) and evidence else "partial"


def keyscore():
    for k, v in load().items():
        put(k, key_score=key_verdict(v))


GATE_MIN_TOLERANCE = 0.10  # never tighter than 2 tickets of 20, even if baseline repeats happen to agree


def _gate_runs(variant, repeats):
    """Run all tickets `repeats` times (no fault) with a prompt variant. Returns per-repeat {ticket: row}."""
    from app.pipeline.triage import run_triage
    os.environ.pop("TRIAGE_FAULT", None)
    os.environ["TRIAGE_PROMPT_VARIANT"] = variant
    reps = []
    for i in range(repeats):
        rows = {}
        for tid in GOLDEN:
            r = run_triage(tid)
            rows[tid] = {"ticket": tid, "trace_id": r["trace_id"], "failed": r["failed"], "reason": r["reason"],
                         "diagnosis": r["diagnosis"]}
            rows[tid]["key_score"] = key_verdict(rows[tid])
        reps.append(rows)
        print(f"  {variant} repeat {i + 1}/{repeats}: correct {sum(v['key_score'] == 'correct' for v in rows.values())}"
              f"/{len(rows)} flagged {sum(v['failed'] for v in rows.values())}", flush=True)
    return reps


def _gate_summary(reps):
    n = len(reps[0])
    correct = [sum(v["key_score"] == "correct" for v in r.values()) / n for r in reps]
    flagged = [sum(v["failed"] for v in r.values()) / n for r in reps]
    frac = {t: sum(r[t]["key_score"] == "correct" for r in reps) / len(reps) for t in reps[0]}
    return {"correct": correct, "flagged": flagged, "ticket_correct_frac": frac}


def gate():
    """Regression gate. `gate baseline [N]` records the reference (N repeats, default 3) and its run-to-run spread.
    `gate <variant> [N]` reruns with that prompt variant and fails (exit 1) if mean correct drops, or mean
    flagged rises, by more than max(0.10, the baseline's own spread)."""
    from app.pipeline.triage import PROMPT_VARIANTS
    variant = sys.argv[2] if len(sys.argv) > 2 else "baseline"
    repeats = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if variant not in PROMPT_VARIANTS:
        sys.exit(f"unknown variant {variant!r}; choose from {list(PROMPT_VARIANTS)}")
    ref_path = ROOT / "data" / "regression_baseline.json"
    summ = _gate_summary(_gate_runs(variant, repeats))
    summ.update(variant=variant, repeats=repeats)
    if variant == "baseline":
        ref_path.write_text(json.dumps(summ, indent=2))
        spread = max(summ["correct"]) - min(summ["correct"])
        print(f"recorded baseline: correct {summ['correct']} (spread {spread:.2f}), flagged {summ['flagged']}")
        return
    if not ref_path.exists():
        sys.exit("no baseline recorded; run: eval_triage.py gate baseline")
    ref = json.loads(ref_path.read_text())
    mean = lambda xs: sum(xs) / len(xs)
    tol_c = max(GATE_MIN_TOLERANCE, max(ref["correct"]) - min(ref["correct"]))
    tol_f = max(GATE_MIN_TOLERANCE, max(ref["flagged"]) - min(ref["flagged"]))
    d_c, d_f = mean(summ["correct"]) - mean(ref["correct"]), mean(summ["flagged"]) - mean(ref["flagged"])
    fail = d_c < -tol_c or d_f > tol_f
    regressed = sorted(t for t, f in ref["ticket_correct_frac"].items() if f - summ["ticket_correct_frac"][t] >= 0.5)
    (ROOT / "data" / f"regression_{variant}.json").write_text(json.dumps(summ, indent=2))
    print(f"variant={variant}  mean correct {mean(summ['correct']):.2f} (baseline {mean(ref['correct']):.2f}, "
          f"{d_c:+.2f}, tolerance {tol_c:.2f})  mean flagged {mean(summ['flagged']):.2f} "
          f"(baseline {mean(ref['flagged']):.2f}, {d_f:+.2f}, tolerance {tol_f:.2f})")
    print("tickets that regressed (correct in >=half more baseline repeats):", regressed or "none")
    print("GATE", "FAIL" if fail else "PASS")
    sys.exit(1 if fail else 0)


def agreement():
    field = sys.argv[2] if len(sys.argv) > 2 else "key_score"
    rows = [{**v, "auto_score": v[field]} for v in load().values() if "score" in v and field in v]
    if not rows:
        sys.exit("No rows with both scores. Run autoscore, and hand-score some rows first.")
    same = sum(v["score"] == v["auto_score"] for v in rows)
    wrongness = sum((v["score"] == "correct") == (v["auto_score"] == "correct") for v in rows)
    print(f"n={len(rows)}  exact agreement={same}/{len(rows)}  correct-vs-not agreement={wrongness}/{len(rows)}")
    for k, v in load().items():
        if "score" in v and field in v and v["score"] != v[field]:
            print(f"  DISAGREE {k}: hand={v['score']} {field}={v[field]}")


def report():
    d = load()
    print(f"{'fault':20} {'n':>2} {'flagged':>7} {'wrong':>5} {'wrong&missed':>12}  reasons")
    for f in FAULTS:
        rs = [v for v in d.values() if v["fault"] == f]
        if not rs:
            continue
        rs = [{**v, "score": (v.get("key_score") if "--key" in sys.argv else v.get("score") or v.get("key_score"))} for v in rs if True]
        scored = [v for v in rs if v["score"]]
        wrong = [v for v in scored if v["score"] != "correct"]
        missed = [v for v in wrong if not v["failed"]]
        reasons = collections.Counter((v["reason"] or "-").split(":")[0] for v in rs if v["failed"])
        print(f"{f:20} {len(rs):>2} {sum(v['failed'] for v in rs):>7} {len(wrong):>5} {len(missed):>12}  {dict(reasons)}"
              + ("" if len(scored) == len(rs) else f"  ({len(rs) - len(scored)} unscored)"))


if __name__ == "__main__":
    {"run": run, "score": score, "autoscore": autoscore, "keyscore": keyscore, "gate": gate, "agreement": agreement, "recheck": recheck, "report": report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
