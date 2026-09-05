"""Budget circuit-breaker engine: the minimal money-safety backstop (Architecture §5.4).

Reserve-then-reconcile against a durable JSONL ledger, restricted to the safety subset needed before
any live paid call. Per-meter ceilings (per-run and per-day) plus an operator kill-switch. Full
per-provider metering, cost events, and forecasts are Stage C and will extend this file.
"""

from __future__ import annotations

import json
import sys
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class BudgetError(RuntimeError):
    """Base class for budget-breaker refusals."""


class BudgetExceededError(BudgetError):
    """A reservation would breach a per-run or per-day ceiling."""


class KillSwitchEngagedError(BudgetError):
    """The operator kill-switch is engaged; no paid call may proceed."""


@dataclass(frozen=True)
class Ceilings:
    """Per-meter spend ceilings. A meter absent from a map is unlimited."""

    per_run: Mapping[str, float]
    per_day: Mapping[str, float]


def _default_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _TokenState:
    reserved_amount: float | None = None
    actual_amount: float | None = None
    meter: str = ""
    run_id: str = ""
    day: date | None = None

    def effective_amount(self) -> float:
        if self.actual_amount is not None:
            return self.actual_amount
        if self.reserved_amount is not None:
            return self.reserved_amount
        return 0.0


def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _as_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _ts_date(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _format_ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                parsed: object = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    return entries


def _token_states(entries: list[dict[str, Any]]) -> dict[str, _TokenState]:
    states: dict[str, _TokenState] = {}
    for entry in entries:
        token = entry.get("token")
        if not isinstance(token, str) or not token:
            continue
        state = states.setdefault(token, _TokenState())
        kind = entry.get("kind")
        if kind == "reserved":
            state.reserved_amount = _as_float(entry.get("amount"))
            meter = _as_str(entry.get("meter"))
            if meter:
                state.meter = meter
            run_id = _as_str(entry.get("run_id"))
            if run_id:
                state.run_id = run_id
            state.day = _ts_date(entry.get("ts"))
        elif kind == "actual":
            state.actual_amount = _as_float(entry.get("amount"))
            if not state.meter:
                state.meter = _as_str(entry.get("meter"))
            if not state.run_id:
                state.run_id = _as_str(entry.get("run_id"))
    return states


def _day_sum(states: Mapping[str, _TokenState], meter: str, today: date) -> float:
    return sum(
        (
            state.effective_amount()
            for state in states.values()
            if state.meter == meter and state.day == today
        ),
        start=0.0,
    )


def _run_sum(states: Mapping[str, _TokenState], run_id: str, meter: str) -> float:
    return sum(
        (
            state.effective_amount()
            for state in states.values()
            if state.run_id == run_id and state.meter == meter
        ),
        start=0.0,
    )


def _append_line(path: Path, record: dict[str, str | float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()


def _lock_exclusive(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        if handle.read(1) == b"":
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_exclusive(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _interprocess_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        _lock_exclusive(handle)
        try:
            yield
        finally:
            _unlock_exclusive(handle)


class BudgetGuard:
    """Enforces ceilings against a JSONL ledger; reserve before a call, reconcile after."""

    def __init__(
        self,
        ledger_path: Path,
        *,
        ceilings: Ceilings,
        kill_switch_path: Path | None = None,
        now: Callable[[], datetime] = _default_now,
    ) -> None:
        self._ledger_path = ledger_path
        self._lock_path = Path(str(ledger_path) + ".lock")
        self._ceilings = ceilings
        self._kill_switch_path = kill_switch_path
        self._now = now
        self._lock = threading.Lock()

    @contextmanager
    def _held(self) -> Iterator[None]:
        with self._lock, _interprocess_lock(self._lock_path):
            yield

    def _snapshot(self) -> dict[str, _TokenState]:
        return _token_states(_read_ledger(self._ledger_path))

    def _record(
        self,
        *,
        token: str,
        run_id: str,
        meter: str,
        unit: str,
        amount: float,
        kind: str,
        note: str,
    ) -> dict[str, str | float]:
        return {
            "ts": _format_ts(self._now()),
            "token": token,
            "run_id": run_id,
            "meter": meter,
            "unit": unit,
            "amount": amount,
            "kind": kind,
            "note": note,
        }

    def reserve(
        self, *, run_id: str, meter: str, unit: str, estimate: float, note: str = ""
    ) -> str:
        with self._held():
            if self._kill_switch_path is not None and self._kill_switch_path.exists():
                raise KillSwitchEngagedError("operator kill-switch is engaged")
            states = self._snapshot()
            today = self._now().astimezone(UTC).date()
            projected_day = _day_sum(states, meter, today) + estimate
            projected_run = _run_sum(states, run_id, meter) + estimate
            if meter in self._ceilings.per_day and projected_day > self._ceilings.per_day[meter]:
                raise BudgetExceededError("per-day ceiling exceeded")
            if meter in self._ceilings.per_run and projected_run > self._ceilings.per_run[meter]:
                raise BudgetExceededError("per-run ceiling exceeded")
            token = uuid.uuid4().hex
            _append_line(
                self._ledger_path,
                self._record(
                    token=token,
                    run_id=run_id,
                    meter=meter,
                    unit=unit,
                    amount=estimate,
                    kind="reserved",
                    note=note,
                ),
            )
            return token

    def reconcile(self, token: str, *, actual: float, note: str = "") -> None:
        with self._held():
            run_id = ""
            meter = ""
            unit = ""
            for entry in _read_ledger(self._ledger_path):
                if entry.get("kind") == "reserved" and entry.get("token") == token:
                    run_id = _as_str(entry.get("run_id"))
                    meter = _as_str(entry.get("meter"))
                    unit = _as_str(entry.get("unit"))
                    break
            _append_line(
                self._ledger_path,
                self._record(
                    token=token,
                    run_id=run_id,
                    meter=meter,
                    unit=unit,
                    amount=actual,
                    kind="actual",
                    note=note,
                ),
            )

    def day_total(self, meter: str) -> float:
        with self._held():
            today = self._now().astimezone(UTC).date()
            return _day_sum(self._snapshot(), meter, today)

    def run_total(self, run_id: str, meter: str) -> float:
        with self._held():
            return _run_sum(self._snapshot(), run_id, meter)
