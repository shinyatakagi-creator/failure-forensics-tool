"""Precision/recall of the failure detector vs hand labels (data/labels.json)."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.storage.db import list_runs


def main():
    path = ROOT / "data" / "labels.json"
    if not path.exists():
        sys.exit("No labels yet. Run: .venv/bin/python scripts/label_runs.py")
    labels = json.loads(path.read_text())
    tp = fp = fn = tn = 0
    for r in list_runs():
        if r["trace_id"] not in labels:
            continue
        truth, pred = labels[r["trace_id"]] == "failed", r["status"] == "failed"
        tp, fp, fn, tn = tp + (truth and pred), fp + (pred and not truth), fn + (truth and not pred), tn + (not truth and not pred)
        if truth != pred:
            print(f"MISS {'FP' if pred else 'FN'} {r['trace_id']} {r['input']!r} -> {r['fail_reason']}")
    n = tp + fp + fn + tn
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    print(f"\nn={n}  (need 30+)\n              pred_failed  pred_ok\ntrue_failed   {tp:>10}  {fn:>7}\ntrue_ok       {fp:>10}  {tn:>7}")
    print(f"precision={prec:.2f} recall={rec:.2f}")


if __name__ == "__main__":
    main()
