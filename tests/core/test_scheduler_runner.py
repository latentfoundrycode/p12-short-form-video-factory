"""F-5 contract (part B): the scheduler runner — bridge the F-2 engine to the runner + a driver.

Architecture: "Scheduling — A timer inside the backend" (§ decisions table) and §5.7: "Reads
`schedules.json`. When an entry is due it checks two conditions … if that workflow already has an
active run, the slot is skipped; if the budget is insufficient, the slot is skipped. Otherwise the
Generation Request starts with the saved settings. Missed slots are skipped rather than queued."

F-2 (`app/core/scheduler.py`) is the PURE engine: `tick(now, schedules_path, state, start, grace)`
computes `dry_run = not entry.allow_real_spend` and calls `start(entry, dry_run)`. This increment
supplies the real `start` (bridging a due entry to `admit_run`) and a `SchedulerDriver` that calls
`tick` on an interval. The §5.7 skip conditions are the runner's existing gates: an active run makes
`admit_run` return `AdmissionBusy`; an insufficient real budget refuses inside the run itself — the
engine records whatever `start` returns, so those become recorded no-spend outcomes rather than
launched work.

`make_scheduler_start` is tested with an injected `admit` spy (deterministic, no subprocess).
`SchedulerDriver.tick_once` is tested synchronously; `start`/`stop` are tested for lifecycle only
(no wall-clock timing assertions).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.scheduler import SchedulerState, TickResult
from app.core.scheduler_runner import (
    SchedulerDeps,
    SchedulerDriver,
    SkippedUnknownWorkflow,
    make_scheduler_start,
)
from app.core.schedules import ScheduleEntry, write_schedules

# 2026-01-05 is a Monday (weekday 0); 07:00 is inside the default grace at exactly the slot time.
DUE_NOW = datetime(2026, 1, 5, 7, 0, 0)


def _entry(**overrides: Any) -> ScheduleEntry:
    base: dict[str, Any] = {
        "id": "sch-1",
        "workflow_id": "explainer",
        "days": [0],
        "time_of_day": "07:00",
        "video_count": 3,
        "concurrency": 1,
        "params": {"topic": "physics"},
        "gates_auto": True,
    }
    base.update(overrides)
    return ScheduleEntry.model_validate(base)


class _AdmitSpy:
    def __init__(self, result: object = "accepted") -> None:
        self.calls: list[dict[str, Any]] = []
        self._result = result

    def __call__(self, workflow_dir: Path, **kwargs: Any) -> object:
        self.calls.append({"workflow_dir": workflow_dir, **kwargs})
        return self._result


def _deps(resolve: Any, admit: Any, runs_dir: Path) -> SchedulerDeps:
    return SchedulerDeps(resolve_workflow=resolve, runs_dir=runs_dir, admit=admit)


# --- make_scheduler_start (the bridge) -------------------------------------------------------


def test_start_launches_known_workflow_through_admit(tmp_path: Path) -> None:
    wf_dir = tmp_path / "wf" / "explainer"
    admit = _AdmitSpy(result="accepted")
    start = make_scheduler_start(
        _deps(lambda wid: wf_dir if wid == "explainer" else None, admit, tmp_path / "runs")
    )
    outcome = start(_entry(), True)
    assert outcome == "accepted"
    assert len(admit.calls) == 1
    call = admit.calls[0]
    assert call["workflow_dir"] == wf_dir
    assert call["params"] == {"topic": "physics"}
    assert call["video_count"] == 3
    assert call["concurrency"] == 1
    assert call["dry_run"] is True
    assert call["runs_dir"] == tmp_path / "runs"


def test_start_forwards_real_spend_as_dry_run_false(tmp_path: Path) -> None:
    admit = _AdmitSpy()
    start = make_scheduler_start(_deps(lambda wid: tmp_path / wid, admit, tmp_path / "runs"))
    start(_entry(allow_real_spend=True), False)
    assert admit.calls[0]["dry_run"] is False


def test_start_skips_unknown_workflow_without_admitting(tmp_path: Path) -> None:
    admit = _AdmitSpy()
    start = make_scheduler_start(_deps(lambda _wid: None, admit, tmp_path / "runs"))
    outcome = start(_entry(workflow_id="ghost"), True)
    assert isinstance(outcome, SkippedUnknownWorkflow)
    assert outcome.workflow_id == "ghost"
    assert admit.calls == []


# --- SchedulerDriver --------------------------------------------------------------------------


def _driver(
    schedules_path: Path, start: Any, *, state: SchedulerState | None = None
) -> SchedulerDriver:
    return SchedulerDriver(
        schedules_path=schedules_path,
        start=start,
        now=lambda: DUE_NOW,
        interval=0.01,
        state=state or SchedulerState(),
    )


def test_tick_once_fires_due_entry_and_returns_results(tmp_path: Path) -> None:
    schedules_path = tmp_path / "schedules.json"
    write_schedules(schedules_path, [_entry()])
    fired: list[tuple[str, bool]] = []

    def start(entry: ScheduleEntry, dry_run: bool) -> str:
        fired.append((entry.id, dry_run))
        return "ok"

    driver = _driver(schedules_path, start)
    results = driver.tick_once()
    assert [r.entry_id for r in results] == ["sch-1"]
    assert isinstance(results[0], TickResult)
    assert results[0].dry_run is True  # allow_real_spend defaults False → dry run
    assert fired == [("sch-1", True)]


def test_tick_once_does_not_refire_same_slot(tmp_path: Path) -> None:
    schedules_path = tmp_path / "schedules.json"
    write_schedules(schedules_path, [_entry()])
    calls = 0

    def start(_entry_arg: ScheduleEntry, _dry: bool) -> None:
        nonlocal calls
        calls += 1

    driver = _driver(schedules_path, start)
    driver.tick_once()
    driver.tick_once()  # same fixed `now` → slot already fired → no second call
    assert calls == 1


def test_tick_once_no_schedule_file_is_noop(tmp_path: Path) -> None:
    calls = 0

    def start(_entry_arg: ScheduleEntry, _dry: bool) -> None:
        nonlocal calls
        calls += 1

    driver = _driver(tmp_path / "absent.json", start)
    assert driver.tick_once() == []
    assert calls == 0


def test_start_then_stop_is_clean(tmp_path: Path) -> None:
    schedules_path = tmp_path / "schedules.json"
    write_schedules(schedules_path, [])

    driver = _driver(schedules_path, lambda _e, _d: None)
    assert driver.running is False
    driver.start()
    assert driver.running is True
    driver.stop()
    assert driver.running is False
