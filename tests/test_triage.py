import os
import pathlib
import sys

os.environ["OPENAI_API_KEY"] = ""  # offline: deterministic fallbacks
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.guardrails import KillSwitchOn, redact
from app.pipeline.triage import run_triage
from app.storage import db
from app.tools.logs import search_logs


def test_redact():
    assert redact("a.b@x.com from 10.0.0.1") == "[email] from [ip]"


def test_triage_end_to_end_pending_approval():
    r = run_triage("T-001")
    assert r["approval"] == "pending_approval"
    assert "idempotency" in r["diagnosis"]["candidates"][0]["cause"]
    assert db.set_approval(r["trace_id"], "approved") is True
    assert db.set_approval(r["trace_id"], "rejected") is False  # decided once


def test_search_logs_statuses():
    assert search_logs("T-001", "idempotency")["status"] == "ok"
    assert search_logs("T-001", "zzz-nope")["status"] == "empty"
    assert search_logs("../x", "a")["status"] == "error"
    assert search_logs("T-001", "(")["status"] == "error"


def test_kill_switch():
    os.environ["TRIAGE_KILL_SWITCH"] = "1"
    try:
        run_triage("T-001")
        assert False
    except KillSwitchOn:
        pass
    finally:
        del os.environ["TRIAGE_KILL_SWITCH"]


if __name__ == "__main__":
    test_redact(); test_triage_end_to_end_pending_approval(); test_search_logs_statuses(); test_kill_switch()
    print("triage tests passed")
