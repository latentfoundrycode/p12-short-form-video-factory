# TASK F-5 fixes — isolate scheduler tick faults (Review B P1)

## Why
Cross-family Review B found a P1: `SchedulerDriver._loop` does not guard `tick_once()`, so ANY
exception raised during a tick (a corrupt `schedules.json` → `read_schedules` raises `ScheduleError`;
an admission/`ensure_env`/run-launch error surfaced through `admit_run`) propagates out of `_loop`,
kills the daemon thread, and permanently stops all scheduling with no retry. A new locking test
(`tests/core/test_scheduler_runner.py::test_driver_survives_a_failing_tick`) is committed and
currently RED.

## Scope
- `app/core/scheduler_runner.py`

## Exact change (apply verbatim; change nothing else)

1. Add a stdlib logger at the top of `app/core/scheduler_runner.py`. Add `import logging` with the
   other stdlib imports (keep imports sorted: `logging` sorts before `subprocess`/`threading`), and
   after the imports (near the `WorkflowResolver` alias) add a module logger:
   ```python
   _log = logging.getLogger(__name__)
   ```

2. Replace the `_loop` method so every tick is guarded — one bad tick logs and the loop continues,
   and it never tears down the daemon thread. Replace this exact block:
   ```python
    def _loop(self) -> None:
        self.tick_once()
        while not self._stop.wait(self._interval):
            self.tick_once()
   ```
   with:
   ```python
    def _loop(self) -> None:
        self._guarded_tick()
        while not self._stop.wait(self._interval):
            self._guarded_tick()

    def _guarded_tick(self) -> None:
        try:
            self.tick_once()
        except Exception:  # noqa: BLE001 - a single bad tick must never kill the scheduler daemon
            _log.exception("scheduler tick failed; skipping this cycle")
   ```

Do NOT change `tick_once` (it must still raise so its synchronous callers/tests see errors), the
lifecycle (`start`/`stop`/`running`), the bridge, `admit_run`, or `app/main.py`. Do NOT catch
`BaseException` (let `KeyboardInterrupt`/`SystemExit` through) — catch `Exception` only.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_scheduler_runner.py -q` → all pass, including
  `test_driver_survives_a_failing_tick`.
- `-m pytest tests/core/test_scheduler_runner.py tests/api/test_admit_run_dry_run.py tests/api/test_scheduler_lifespan.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
