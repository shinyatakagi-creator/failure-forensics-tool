import pathlib
import re

from app.tools import fault, mark

LOGS_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "logs"
MAX_LINES = 20


def search_logs(ticket_id: str, pattern: str) -> dict:
    """Regex-search one ticket's log file. Never raises: failures come back as status='error'."""
    try:
        if not re.fullmatch(r"T-\d+", ticket_id):  # ticket_id comes from the API: no path tricks
            raise ValueError(f"bad ticket id {ticket_id!r}")
        if fault() == "tool_throws":
            raise OSError("injected fault: log backend unavailable")
        rx = re.compile(pattern, re.IGNORECASE)
        all_lines = (LOGS_DIR / f"{ticket_id}.log").read_text().splitlines()
        if fault() == "remove_logs":  # drop every WARN/ERROR line, keep the noise
            all_lines = [l for l in all_lines if " WARN " not in l and " ERROR " not in l]
        lines = [l for l in all_lines if rx.search(l)][:MAX_LINES]
    except Exception as e:
        mark("search_logs", "error", f"{type(e).__name__}: {e}")
        return {"status": "error", "lines": [], "error": str(e)}
    status = "ok" if lines else "empty"
    mark("search_logs", status)
    return {"status": status, "lines": lines}
