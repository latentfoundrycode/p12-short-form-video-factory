"""Scheduler engine: which schedule entries fire at a given moment (Architecture §5.7).

Reads schedules.json via the schedules data layer. An entry is due when its weekday matches, the
current time is inside a short grace window after ``time_of_day``, and the slot has not already
fired. Missed slots (the app was down through the window) are skipped, never queued. Each due
entry is handed to an injected ``start`` callable; scheduled runs default to a free dry run
unless the entry opts into real spend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from app.core.schedules import ScheduleEntry, read_schedules

# Window after a slot's time within which it still fires. Past this, the slot is missed.
DEFAULT_GRACE = timedelta(minutes=5)

type StartFn = Callable[[ScheduleEntry, bool], object]


@dataclass
class SchedulerState:
    """Already-fired slot keys across ticks. Constructible with no args."""

    fired: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class TickResult:
    """Outcome of firing one due schedule entry during a tick."""

    entry_id: str
    dry_run: bool
    outcome: object


def slot_key(entry: ScheduleEntry, now: datetime) -> str:
    """Stable identity for one entry's slot on one calendar day."""
    return f"{entry.id}|{now.date().isoformat()}|{entry.time_of_day}"


def _slot_time(entry: ScheduleEntry, now: datetime) -> datetime:
    hour_s, minute_s = entry.time_of_day.split(":")
    return now.replace(hour=int(hour_s), minute=int(minute_s), second=0, microsecond=0)


def due_entries(
    entries: list[ScheduleEntry],
    now: datetime,
    fired: set[str],
    *,
    grace: timedelta = DEFAULT_GRACE,
) -> list[ScheduleEntry]:
    """Return entries whose slot is in-window at ``now`` and has not already fired.

    Order of ``entries`` is preserved. A ``now`` before the slot time, on a non-matching weekday,
    past the grace window, or whose ``slot_key`` is already in ``fired`` is not due.
    """
    matching: list[ScheduleEntry] = []
    for entry in entries:
        if now.weekday() not in entry.days:
            continue
        due = _slot_time(entry, now)
        if not (due <= now < due + grace):
            continue
        if slot_key(entry, now) in fired:
            continue
        matching.append(entry)
    return matching


def tick(
    now: datetime,
    *,
    schedules_path: Path,
    state: SchedulerState,
    start: StartFn,
    grace: timedelta = DEFAULT_GRACE,
) -> list[TickResult]:
    """Fire each due entry through ``start`` and record the slot as fired.

    ``start`` is called as ``start(entry, dry_run)`` with ``dry_run = not entry.allow_real_spend``.
    A missing schedules file yields no entries, so the tick does nothing.
    """
    results: list[TickResult] = []
    for entry in due_entries(read_schedules(schedules_path), now, state.fired, grace=grace):
        dry_run = not entry.allow_real_spend
        outcome = start(entry, dry_run)
        state.fired.add(slot_key(entry, now))
        results.append(TickResult(entry_id=entry.id, dry_run=dry_run, outcome=outcome))
    return results
