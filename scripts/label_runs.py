"""Hand-label runs as failed/ok. Labels go to data/labels.json. Usage: python scripts/label_runs.py"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.storage.db import list_runs
from app.storage.traces import read_trace_file

LABELS = ROOT / "data" / "labels.json"


def main():
    labels = json.loads(LABELS.read_text()) if LABELS.exists() else {}
    for run in list_runs():
        if run["trace_id"] in labels:
            continue
        t = read_trace_file(run["trace_id"]) or {}
        # Deliberately hide the detector's verdict so labels aren't biased by it.
        print(f"\nQ: {run['input']!r}\nContext: {(t.get('context') or '')[:200]!r}\n"
              f"Tool: {t.get('tool_result')}\nA: {run['output']!r}")
        c = input("[f]ailed / [o]k / [s]kip / [q]uit: ").strip().lower()
        if c == "q":
            break
        if c in ("f", "o"):
            labels[run["trace_id"]] = "failed" if c == "f" else "ok"
            LABELS.write_text(json.dumps(labels, indent=2))
    print(f"{len(labels)} labelled")


if __name__ == "__main__":
    main()
