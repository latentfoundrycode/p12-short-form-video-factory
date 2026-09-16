# TASK — H-2: plumb `gates_auto` into the run context + scheduler bridge

## Goal (one sentence)
Thread the per-schedule gate-bypass flag from admission into each video's `context.json` (as
`gates_auto`), and have the scheduler bridge forward `entry.gates_auto`, so an unattended scheduled
run resolves `ctx.gate()` via `on_bypass` instead of parking with nobody to answer.

## Background (already done)
- The SDK reads `ctx.gates_auto` (H-1, merged): `ContextFile.gates_auto` already exists and defaults
  `False`; a bypassed gate returns `on_bypass` without blocking.
- The silence watchdog already skips the kill while a gate is open
  (`app/core/supervisor.py` `_SilenceState.gate_open` → `_watch_silence` `continue`). Do NOT touch it.
- `ScheduleEntry.gates_auto: bool` already exists.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_supervisor.py` (`test_run_request_injects_gates_auto_into_context`,
`test_run_request_defaults_gates_auto_false`) and
`tests/core/test_scheduler_runner.py` (`test_start_passes_gates_auto_through`). All existing tests
must stay green.

## What to change

### 1. `app/core/supervisor.py`
- Add `gates_auto: bool = False` to the `_ContextWiring` dataclass (with the other run-wide fields).
- Add a `gates_auto: bool = False` keyword parameter to `run_request(...)`, and set
  `gates_auto=gates_auto` in the `_ContextWiring(...)` construction (around line 433).
- In `_make_context(...)`, pass `gates_auto=wiring.gates_auto` to the `ContextFile(...)` it builds
  (so it lands in every video's `context.json`).

### 2. `app/api/runs.py`
- Add a `gates_auto: bool = False` keyword parameter to `admit_run(...)` and forward it to its
  internal `run_request(...)` call. (Interactive API launches never set it → stays False.)

### 3. `app/core/scheduler_runner.py`
- In `make_scheduler_start`'s `start(entry, dry_run)`, pass `gates_auto=entry.gates_auto` to the
  `deps.admit(...)` call.

## Constraints / do-nots
- Touch ONLY `app/core/supervisor.py`, `app/api/runs.py`, `app/core/scheduler_runner.py`. Do NOT
  edit any test or other file.
- Do NOT change the silence watchdog / `gate_open` handling — already correct.
- Interactive/manual runs must default to `gates_auto=False` (never bypass a gate when a user is
  present).
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/core/supervisor.py`
- `app/api/runs.py`
- `app/core/scheduler_runner.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_supervisor.py tests/core/test_scheduler_runner.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
