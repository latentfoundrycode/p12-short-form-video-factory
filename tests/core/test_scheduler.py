"""F-2 contract: the scheduler engine (Architecture §5.7).

§5.7: "When an entry is due it checks two conditions … if that workflow already has an active run,
the slot is skipped; if the budget is insufficient, the slot is skipped. Otherwise the Generation
Request starts with the saved settings. Missed slots are skipped rather than queued."

The engine is pure + injectable: `due_entries` decides which entries fire at a given `now` (weekday
match, within a short grace window after `time_of_day`, not already fired this slot) — so a slot the
app was down for is simply never in-window again and is skipped, never queued. `tick` fires each due
entry through an injected `start(entry, dry_run)` and records the outcome; per the owner decision
it derives `dry_run = not entry.allow_real_spend`, so a default entry runs as a free dry run. The
active/budget skips are the runner's existing gates (AdmissionBusy / AdmissionBlocked) via `start`.
No real runs are started here (start is injected).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.scheduler import DEFAULT_GRACE, SchedulerState, due_entries, slot_key, tick
from app.core.schedules import ScheduleEntry, write_schedules

# 2026-01-05 is a Monday (weekday 0).
MON_0700 = datetime(2026, 1, 5, 7, 0, 0)


def _entry(**overrides: object) -> ScheduleEntry:
    base: dict[str, object] = {
        "id": "sch-1",
        "workflow_id": "explainer",
        "days": [0],  # Monday
        "time_of_day": "07:00",
        "video_count": 2,
        "params": {},
        "gates_auto": True,
    }
    base.update(overrides)
    return ScheduleEntry.model_validate(base)


# --- due_entries: weekday / time-of-day / grace window / already-fired ---


def test_due_at_the_slot_time_on_a_matching_weekday() -> None:
    assert due_entries([_entry()], MON_0700, set()) == [_entry()]


def test_due_within_the_grace_window() -> None:
    within = MON_0700 + DEFAULT_GRACE - timedelta(seconds=1)
    assert due_entries([_entry()], within, set()) == [_entry()]


def test_not_due_before_the_slot_time() -> None:
    assert due_entries([_entry()], MON_0700 - timedelta(minutes=1), set()) == []


def test_missed_slot_past_the_grace_window_is_skipped() -> None:
    # App was down through the window and ticks late — the slot is NOT fired (not queued).
    late = MON_0700 + DEFAULT_GRACE + timedelta(minutes=1)
    assert due_entries([_entry()], late, set()) == []


def test_not_due_on_a_non_matching_weekday() -> None:
    tue_0700 = MON_0700 + timedelta(days=1)  # Tuesday, weekday 1, not in days=[0]
    assert due_entries([_entry()], tue_0700, set()) == []


def test_already_fired_slot_is_not_due_again() -> None:
    fired = {slot_key(_entry(), MON_0700)}
    assert due_entries([_entry()], MON_0700, fired) == []


def test_slot_key_is_stable_within_a_slot_and_distinct_across_days() -> None:
    e = _entry()
    assert slot_key(e, MON_0700) == slot_key(e, MON_0700 + timedelta(seconds=30))
    assert slot_key(e, MON_0700) != slot_key(e, MON_0700 + timedelta(days=7))  # next Monday


# --- tick: dry_run derivation (OWNER decision), fire-once, outcome recording ---


def _calls() -> list[tuple[str, bool]]:
    return []


def test_tick_default_entry_fires_dry_run(tmp_path) -> None:
    # Owner decision: allow_real_spend defaults False → the scheduled run is a free dry run.
    path = tmp_path / "schedules.json"
    write_schedules(path, [_entry()])
    state = SchedulerState()
    calls: list[tuple[str, bool]] = []
    tick(MON_0700, schedules_path=path, state=state, start=_recorder(calls))
    assert calls == [("sch-1", True)]


def test_tick_opted_in_entry_fires_real(tmp_path) -> None:
    path = tmp_path / "schedules.json"
    write_schedules(path, [_entry(allow_real_spend=True)])
    state = SchedulerState()
    calls: list[tuple[str, bool]] = []
    tick(MON_0700, schedules_path=path, state=state, start=_recorder(calls))
    assert calls == [("sch-1", False)]  # dry_run False == real spend


def test_tick_fires_a_slot_only_once(tmp_path) -> None:
    path = tmp_path / "schedules.json"
    write_schedules(path, [_entry()])
    state = SchedulerState()
    calls: list[tuple[str, bool]] = []
    start = _recorder(calls)
    tick(MON_0700, schedules_path=path, state=state, start=start)
    # A second tick still inside the grace window must NOT re-fire the same slot.
    tick(MON_0700 + timedelta(seconds=30), schedules_path=path, state=state, start=start)
    assert calls == [("sch-1", True)]


def test_tick_with_no_schedules_file_does_nothing(tmp_path) -> None:
    state = SchedulerState()
    calls: list[tuple[str, bool]] = []
    tick(MON_0700, schedules_path=tmp_path / "none.json", state=state, start=_recorder(calls))
    assert calls == []


def _recorder(calls: list[tuple[str, bool]]):
    def start(entry: ScheduleEntry, dry_run: bool) -> str:
        calls.append((entry.id, dry_run))
        return "started"

    return start
