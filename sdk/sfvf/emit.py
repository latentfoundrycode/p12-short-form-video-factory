import json
import sys
from typing import Any


def emit(event: dict[str, Any]) -> None:
    """Write one compact JSON object to stdout and flush so a reader sees it immediately."""
    sys.stdout.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(msg: str, *, level: str = "info") -> None:
    emit({"t": "log", "level": level, "msg": msg})


def stage(index: int, total: int, label: str) -> None:
    emit({"t": "stage", "index": index, "total": total, "label": label})


def heartbeat(name: str, *, waiting_on: str, key: str | None = None) -> None:
    event: dict[str, Any] = {"t": "heartbeat", "name": name, "waiting_on": waiting_on}
    if key is not None:
        event["key"] = key
    emit(event)
