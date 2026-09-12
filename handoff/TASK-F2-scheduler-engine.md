# TASK F-2 — scheduler engine (§5.7)

## Goal (one sentence)
Create `app/core/scheduler.py` — the pure engine that decides which `ScheduleEntry` fire at a given
moment (skipping missed slots) and fires each due entry through an injected `start` callable, running
it dry unless the entry opted into real spend.

## Governing spec (verbatim — Architecture §5.7)
> Reads `schedules.json`. When an entry is due it checks two conditions and acts accordingly: if that
> workflow already has an active run, the slot is skipped; if the budget is insufficient, the slot is
> skipped. Otherwise the Generation Request starts with the saved settings.
>
> Missed slots are skipped rather than queued, because a queue would silently accumulate runs and
> then execute several at once …
>
> Each entry carries the flag determining whether approval gates pause or pass automatically.

Owner decision (2026-09-12): scheduled runs default to a free **dry run**; the engine derives
`dry_run = not entry.allow_real_spend`. The two skip conditions (active run / insufficient budget)
are the RUNNER's existing gates — this engine delegates firing to an injected `start` callable and
records the outcome; wiring `start` to the real runner and running the engine on a timer is a
follow-on increment (do NOT build the background thread or touch the API/runner here).

## Frozen contract (already committed — do NOT edit)
`tests/core/test_scheduler.py`. It imports and pins this exact surface from `app.core.scheduler`:
- `DEFAULT_GRACE` — a `datetime.timedelta` (the window after a slot's time within which it still
  fires; pick a small default, e.g. 5 minutes — the contract uses `DEFAULT_GRACE` symbolically).
- `class SchedulerState` — holds the set of already-fired slot keys across ticks (an in-memory
  `fired: set[str]`; constructible with no args).
- `slot_key(entry: ScheduleEntry, now: datetime) -> str` — stable within one slot, distinct across
  days (e.g. `f"{entry.id}|{now.date().isoformat()}|{entry.time_of_day}"`).
- `due_entries(entries: list[ScheduleEntry], now: datetime, fired: set[str], *, grace: timedelta =
  DEFAULT_GRACE) -> list[ScheduleEntry]`.
- `tick(now: datetime, *, schedules_path: Path, state: SchedulerState, start: StartFn, grace:
  timedelta = DEFAULT_GRACE) -> <list of per-entry results>` where `StartFn` is
  `Callable[[ScheduleEntry, bool], object]` called as `start(entry, dry_run)`.

## What to implement (`app/core/scheduler.py` only)

### `due_entries`
An entry is due at `now` when ALL hold:
- `now.weekday()` (Monday=0 … Sunday=6) is in `entry.days`.
- The slot time today has arrived but not long passed: with `due = now` at `entry.time_of_day`
  (parse `"HH:MM"`), `due <= now < due + grace`. So a `now` before the slot time is NOT due, and a
  `now` past the grace window (the app was down through it) is NOT due — a MISSED slot is skipped,
  never fired late or queued.
- `slot_key(entry, now)` is NOT in `fired`.
Return the matching entries (order preserved).

### `slot_key`
Return a stable per-slot identity so a slot fires once: include the entry id, the date, and the
`time_of_day`. Two `now`s within the same slot/day give the same key; the next week's slot gives a
different key.

### `tick`
- `entries = read_schedules(schedules_path)` (from `app.core.schedules`; a missing file → `[]`, so a
  no-schedules tick does nothing).
- `for entry in due_entries(entries, now, state.fired, grace=grace):`
  - `dry_run = not entry.allow_real_spend` (owner decision).
  - `result = start(entry, dry_run)` — delegate the actual launch to the injected callable.
  - `state.fired.add(slot_key(entry, now))` — so the slot does not re-fire on a later in-window tick.
  - collect a per-entry result (e.g. a small frozen dataclass `TickResult(entry_id, dry_run,
    outcome)` where `outcome` is derived from/echoes `result`, or a tuple) — the contract only
    checks the `start` calls and fire-once behaviour, so keep the return simple and typed.
- Return the collected results.

## Constraints / do-nots
- Only create `app/core/scheduler.py`. Do NOT edit any test, `app/core/schedules.py`,
  `app/core/supervisor.py`, `app/api/*`, or the frontend. Do NOT build the background timer/thread,
  wire a real `start` to `admit_run`/`run_request`, or thread `dry_run` through `admit_run` — that is
  the follow-on wiring increment. Do NOT add a dependency (stdlib + the existing model only).
- Keep `ruff check`, `ruff format`, and `mypy --strict` clean; match the surrounding style. Use
  naive local `datetime` (schedules are wall-clock `HH:MM`); do not introduce timezone handling.

## Scope
- `app/core/scheduler.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_scheduler.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
