# TASK — persist scheduler fired-slots across restart (H39.1)

## Why
`SchedulerState.fired` is in-memory and the driver runs `tick_once()` immediately on startup, so an
app restart INSIDE a slot's 5-min grace window re-fires an already-fired slot — for an
`allow_real_spend=True` entry that is a DUPLICATE real-money run. Fix: persist fired-slot keys to
disk (pruned to the current day so the file cannot grow forever), seed `SchedulerState` from that
file when the driver is constructed, and write after each fire — so a restarted, disk-seeded state
does not re-fire.

Frozen RED tests (committed, do not modify):
- `tests/core/test_scheduler.py`: `test_tick_persists_the_fired_slot`,
  `test_read_fired_missing_or_corrupt_is_empty`,
  `test_restart_within_grace_seeded_from_disk_does_not_refire`,
  `test_write_fired_prunes_keys_from_other_days`.
- `tests/core/test_scheduler_runner.py`: `test_driver_seeds_fired_from_disk_and_does_not_refire`.

## Changes

### 1. `app/core/scheduler.py` — persistence helpers + `fired_path` on `tick`
Add imports at the top: `import json`, `from datetime import date` (extend the existing datetime
import line), and `from app.core.records import write_json_value_atomic`.

Add these helpers (near `slot_key`):
```python
def _slot_key_date(key: str) -> date | None:
    # slot_key is f"{entry.id}|{date}|{time_of_day}"; rsplit so an id containing "|" is tolerated.
    parts = key.rsplit("|", 2)
    if len(parts) != 3:
        return None
    try:
        return date.fromisoformat(parts[1])
    except ValueError:
        return None


def read_fired(path: Path) -> set[str]:
    """Load persisted fired slot keys. Best-effort: a missing/corrupt/non-list file yields set()."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {k for k in data if isinstance(k, str)}


def write_fired(path: Path, fired: set[str], *, today: date) -> None:
    """Persist fired slot keys for `today` only (older days pruned), atomically. Best-effort:
    a filesystem failure is swallowed — the on-disk budget ledger still bounds any re-fire."""
    keys = sorted(k for k in fired if _slot_key_date(k) == today)
    try:
        write_json_value_atomic(path, keys)
    except OSError:
        return
```

Extend `tick` with an optional `fired_path`, and persist after each fire:
```python
def tick(
    now: datetime,
    *,
    schedules_path: Path,
    state: SchedulerState,
    start: StartFn,
    grace: timedelta = DEFAULT_GRACE,
    fired_path: Path | None = None,
) -> list[TickResult]:
    ...
    for entry in due_entries(read_schedules(schedules_path), now, state.fired, grace=grace):
        dry_run = not entry.allow_real_spend
        outcome = start(entry, dry_run)
        state.fired.add(slot_key(entry, now))
        if fired_path is not None:
            write_fired(fired_path, state.fired, today=now.date())
        results.append(TickResult(entry_id=entry.id, dry_run=dry_run, outcome=outcome))
    return results
```
(Persist AFTER `state.fired.add`, per fire, so each fired slot is durable immediately. Keep the
docstring; the `start(entry, dry_run)` ordering is unchanged.)

### 2. `app/core/scheduler_runner.py` — `SchedulerDriver` seeds from disk, passes `fired_path`
Add a `fired_path: Path | None = None` keyword parameter to `SchedulerDriver.__init__`. Store it.
Seed the state from disk when no explicit `state` is provided:
```python
    def __init__(
        self,
        *,
        schedules_path: Path,
        start: StartFn,
        now: Callable[[], datetime] = datetime.now,
        interval: float = 60.0,
        grace: timedelta = DEFAULT_GRACE,
        state: SchedulerState | None = None,
        fired_path: Path | None = None,
    ) -> None:
        self._schedules_path = schedules_path
        self._start = start
        self._now = now
        self._interval = interval
        self._grace = grace
        self._fired_path = fired_path
        if state is not None:
            self._state = state
        elif fired_path is not None:
            self._state = SchedulerState(fired=read_fired(fired_path))
        else:
            self._state = SchedulerState()
        ...  # the threading.Event/lock/thread fields UNCHANGED
```
Import `read_fired` from `app.core.scheduler` (extend the existing import). In `tick_once`, pass the
path through:
```python
    def tick_once(self) -> list[TickResult]:
        return tick(
            self._now(),
            schedules_path=self._schedules_path,
            state=self._state,
            start=self._start,
            grace=self._grace,
            fired_path=self._fired_path,
        )
```

### 3. `app/main.py` — give the driver a `fired_path`
Where the `SchedulerDriver(...)` is constructed in the scheduler lifespan (currently
`schedules_path=` + `start=`), add:
```python
            driver = SchedulerDriver(
                schedules_path=scheduler_schedules_path,
                start=make_scheduler_start(deps),
                fired_path=scheduler_schedules_path.parent / "scheduler_fired.json",
            )
```

## Scope / do NOT
- Only `app/core/scheduler.py`, `app/core/scheduler_runner.py`, `app/main.py`. Do NOT change
  `due_entries`, `slot_key`, `SchedulerState`'s fields, the schedules data layer, any test, or any
  stub. No new dependencies (reuse `write_json_value_atomic` from `app.core.records`).
- H39.2 (`gates_auto` runtime) and H39.3 (shutdown join) are OUT OF SCOPE — do not touch them.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/core/test_scheduler.py tests/core/test_scheduler_runner.py -q`
  → all pass (the new persistence/restart/prune tests plus every existing scheduler test — the
  in-memory fire-once behaviour must stay green).
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
