# TASK-h39-3 — bound SchedulerDriver.stop()'s join

## Goal

Close H39(3). `SchedulerDriver.stop()` holds `_lifecycle_lock` across `self._thread.join()` with no timeout, so a stop issued while a tick is mid-`admit_run`/`ensure_env` (e.g. a first-time venv build) blocks for that whole duration. The scheduler thread is a daemon (so this can't hang process exit), but a graceful in-app stop should not wall on a slow tick. Give `stop()` a bounded join.

## The one file to change

`app/core/scheduler_runner.py` only. Do not touch any test or any other module. Frozen contract: `tests/core/test_scheduler_stop.py`.

## Current code

```python
    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is None:
                return
            self._thread.join()
```

## The change

Give `stop` a keyword-only `timeout: float = _STOP_TIMEOUT_S` and pass it to `join`:

```python
    def stop(self, *, timeout: float = _STOP_TIMEOUT_S) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is None:
                return
            self._thread.join(timeout)
```

Add a module-level constant `_STOP_TIMEOUT_S: float = 5.0` (a finite default: long enough for a normal tick to finish, short enough that a graceful stop stays responsive; the daemon thread is reclaimed at process exit if it outlives the bound). `self._stop.set()` still fires first so the loop will exit at its next check regardless; the bounded join only decides how long `stop()` waits for an in-progress tick.

That is the whole change. Do not otherwise alter the lifecycle (`start`, `running`, `_loop`, `tick_once`).

## Constraints

- Behaviour-preserving for the normal path: a driver whose tick is fast still stops and its thread ends well within the default timeout; a never-started driver still returns immediately (`_thread is None`).
- Keep `stop()` callable with no arguments (the default timeout applies) — existing callers (e.g. `app/main.py`) must not need changes.
- No new dependency. One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_scheduler_stop.py` is fully green (the bounded-stop test currently fails: `stop()` takes no `timeout`).
- `tests/core/test_scheduler_runner.py` stays green (lifecycle unchanged).
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
