import json
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_lock = threading.Lock()


def emit(event: dict[str, Any]) -> None:
    """Write one compact JSON object to stdout and flush so a reader sees it immediately."""
    line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _lock:
        sys.stdout.write(line)
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


_HEARTBEAT_INTERVAL_S = 30.0  # < the 300 s silence watchdog, with a wide margin


@contextmanager
def heartbeat_during(
    name: str, *, waiting_on: str, interval: float = _HEARTBEAT_INTERVAL_S, key: str | None = None
) -> Iterator[None]:
    """Emit a `heartbeat` every `interval` seconds from a daemon thread until the block exits, so a
    long blocking local op (FFmpeg) keeps the supervisor's silence watchdog fed. The first heartbeat
    is one interval in, so an op faster than `interval` emits none. Never raises from the thread."""
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(interval):
            heartbeat(name, waiting_on=waiting_on, key=key)

    thread = threading.Thread(target=_loop, name=f"sfvf-heartbeat-{name}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5.0)


def decision(
    kind: str,
    chosen: str,
    *,
    alternatives: list[str] | None = None,
    reason: str | None = None,
) -> None:
    event: dict[str, Any] = {"t": "decision", "kind": kind, "chosen": chosen}
    if alternatives is not None:
        event["alternatives"] = alternatives
    if reason is not None:
        event["reason"] = reason
    emit(event)


def forecast(meter: str, unit: str, amount: float, *, note: str | None = None) -> None:
    event: dict[str, Any] = {"t": "forecast", "meter": meter, "unit": unit, "amount": amount}
    if note is not None:
        event["note"] = note
    emit(event)
