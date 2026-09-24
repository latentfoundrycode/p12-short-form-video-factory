"""H39(3) contract: SchedulerDriver.stop() is bounded, not an unbounded join under the lock.

`stop()` held `_lifecycle_lock` across `self._thread.join()` with no timeout, so if a tick was
mid-`admit_run`/`ensure_env` (e.g. a first-time venv build) shutdown blocked for that duration. The
scheduler thread is a daemon (so a blocked stop can't hang process exit), but a graceful in-app stop
should not wall on a slow tick. `stop(*, timeout=...)` now bounds the join: it returns after the
timeout even if the current tick has not finished; the daemon thread finishes (or is reclaimed at
process exit) on its own.

Deterministic and event-synced — no wall-clock duration assertions (per the runner test convention),
and every wait is bounded so a regression cannot hang the suite.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.scheduler import SchedulerState
from app.core.scheduler_runner import SchedulerDriver
from app.core.schedules import ScheduleEntry, write_schedules

DUE_NOW = datetime(2026, 1, 5, 7, 0, 0)  # Monday 07:00 — inside the default grace at the slot time


def _entry(**overrides: Any) -> ScheduleEntry:
    base: dict[str, Any] = {
        "id": "sch-1",
        "workflow_id": "explainer",
        "days": [0],
        "time_of_day": "07:00",
        "video_count": 1,
        "concurrency": 1,
        "params": {},
        "gates_auto": True,
    }
    base.update(overrides)
    return ScheduleEntry.model_validate(base)


def test_stop_with_no_running_thread_returns(tmp_path: Path) -> None:
    driver = SchedulerDriver(
        schedules_path=tmp_path / "schedules.json",
        start=lambda _e, _d: None,
        now=lambda: DUE_NOW,
        interval=0.01,
        state=SchedulerState(),
    )
    driver.stop()  # never started → returns immediately
    assert driver.running is False


def test_stop_does_not_block_on_an_in_progress_tick(tmp_path: Path) -> None:
    schedules_path = tmp_path / "schedules.json"
    write_schedules(schedules_path, [_entry()])
    entered = threading.Event()
    release = threading.Event()

    def start(_entry_arg: ScheduleEntry, _dry: bool) -> str:
        entered.set()
        release.wait(timeout=5.0)  # the tick blocks here; bounded so nothing hangs if the test errs
        return "ok"

    driver = SchedulerDriver(
        schedules_path=schedules_path,
        start=start,
        now=lambda: DUE_NOW,
        interval=0.01,
        state=SchedulerState(),
    )
    driver.start()
    try:
        assert entered.wait(timeout=2.0)  # the immediate startup tick is now blocked inside start
        driver.stop(timeout=0.1)  # bounded: must return without waiting out the blocked tick
        # The join was bounded, so the still-blocked daemon thread is left running — stop did not
        # wall on it. (An unbounded join would only return after the tick released ~5 s later.)
        assert driver.running is True
    finally:
        release.set()  # unblock the tick so the daemon thread observes _stop and exits cleanly
