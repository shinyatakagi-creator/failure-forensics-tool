import os
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


class KillSwitchOn(RuntimeError):
    pass


def redact(text: str) -> str:
    return _IP.sub("[ip]", _EMAIL.sub("[email]", text))


def check_kill_switch() -> None:
    if os.environ.get("TRIAGE_KILL_SWITCH"):
        raise KillSwitchOn("TRIAGE_KILL_SWITCH is set")
