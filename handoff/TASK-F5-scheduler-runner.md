# TASK F-5 — scheduler runner wiring (§5.7, "a timer inside the backend")

## Goal (one sentence)
Make the scheduler actually launch runs: thread `dry_run` through `admit_run`, add
`app/core/scheduler_runner.py` (a `start` bridge from a due `ScheduleEntry` to `admit_run` + a
`SchedulerDriver` that ticks the F-2 engine on an interval), and arm that driver from the app
lifespan — opt-in, off by default.

## Governing spec (verbatim — Architecture §5.7 + the decisions table)
> Reads `schedules.json`. When an entry is due it checks two conditions and acts accordingly: if that
> workflow already has an active run, the slot is skipped; if the budget is insufficient, the slot is
> skipped. Otherwise the Generation Request starts with the saved settings.
>
> Missed slots are skipped rather than queued …

Decisions table: "Scheduling — A timer inside the backend — The backend is already running
continuously; adding an external scheduler would introduce a second thing that must also be running."

Owner decision (2026-09-12): a scheduled run defaults to a free **dry run**; the F-2 engine already
computes `dry_run = not entry.allow_real_spend`. Real spend is per-entry opt-in and still
budget-capped. Nothing in this increment may spend money on its own.

## Frozen contract (already committed — do NOT edit)
- `tests/api/test_admit_run_dry_run.py`
- `tests/core/test_scheduler_runner.py`
- `tests/api/test_scheduler_lifespan.py`

Read them as the source of truth. The notes below explain intent.

## What to implement

### 1. `app/api/runs.py` — thread `dry_run` through `admit_run`
- Add a keyword parameter `dry_run: bool = False` to `admit_run(...)` (place it among the other
  keyword-only params).
- Pass it into the `run_request(...)` call inside `admit_run`'s `target()` as `dry_run=dry_run`.
  `run_request` already accepts `dry_run` and honours it. Change NOTHING else in `admit_run`, and do
  NOT add `dry_run` to the HTTP `LaunchBody` / `launch_run` endpoint — the UI launch path stays real.

### 2. `app/core/scheduler_runner.py` (new)
Imports it will need: `from __future__ import annotations`; `threading`, `time`, `subprocess`;
`from collections.abc import Callable, Mapping`; `from dataclasses import dataclass, field`;
`from datetime import datetime`; `from pathlib import Path`; `from sfvf.context import BudgetConfig`;
`from app.api.runs import AdmissionResult, admit_run`; `from app.core.env import ensure_env as
default_ensure_env`; `from app.core.supervisor import EnsureEnv, PopenFn`; `from app.core.scheduler
import DEFAULT_GRACE, SchedulerState, StartFn, TickResult, tick`; `from app.core.schedules import
ScheduleEntry`.

Define:
```python
type WorkflowResolver = Callable[[str], Path | None]  # workflow_id -> its dir, or None if unknown

@dataclass(frozen=True)
class SkippedUnknownWorkflow:
    workflow_id: str

@dataclass(frozen=True)
class SchedulerDeps:
    resolve_workflow: WorkflowResolver
    runs_dir: Path
    ensure_env: EnsureEnv = default_ensure_env
    popen: PopenFn = subprocess.Popen
    secrets: Mapping[str, str] | None = None
    budget: BudgetConfig | None = None
    admit: Callable[..., AdmissionResult] = admit_run   # injectable for tests
```

`make_scheduler_start(deps: SchedulerDeps) -> StartFn` returns a `start(entry, dry_run)` that:
- resolves `wd = deps.resolve_workflow(entry.workflow_id)`; if `None`, returns
  `SkippedUnknownWorkflow(entry.workflow_id)` and does NOT admit (a due slot for a workflow the
  registry doesn't know is skipped, per §5.7's spirit — nothing to start);
- otherwise returns
  `deps.admit(wd, params=entry.params, video_count=entry.video_count,
  concurrency=entry.concurrency, dry_run=dry_run, runs_dir=deps.runs_dir,
  ensure_env=deps.ensure_env, popen=deps.popen, secrets=deps.secrets, budget=deps.budget)`.
  (The §5.7 skips are the runner's existing gates: an active run → `AdmissionBusy`; a real budget
  short → the run self-refuses `stopped-budget` inside `run_request`. The engine records whatever is
  returned — do not add extra skip logic here.)

`SchedulerDriver` — a thin periodic driver around the F-2 `tick`:
```python
class SchedulerDriver:
    def __init__(self, *, schedules_path: Path, start: StartFn,
                 now: Callable[[], datetime] = datetime.now,
                 interval: float = 60.0, grace: timedelta = DEFAULT_GRACE,
                 state: SchedulerState | None = None) -> None: ...
    @property
    def running(self) -> bool: ...
    def tick_once(self) -> list[TickResult]:
        return tick(self._now(), schedules_path=self._schedules_path,
                    state=self._state, start=self._start, grace=self._grace)
    def start(self) -> None:   # idempotent; spawn ONE daemon thread running the loop
    def stop(self) -> None:    # signal + join; running -> False
```
Loop shape (fire immediately, then every `interval`, exit promptly on stop) — use a
`threading.Event` so stop is responsive, not a bare sleep:
```python
def _loop(self) -> None:
    self.tick_once()
    while not self._stop.wait(self._interval):
        self.tick_once()
```
`now` defaults to `datetime.now` (naive local wall-clock, matching the F-2 engine; the DST /
near-midnight-grace edges are tracked in HARDENING H36 — do not add timezone handling here). Guard
`start()`/`stop()` so double-calls are safe and `running` reflects the true thread state.

### 3. `app/main.py` — arm the driver from the lifespan, opt-in
- Add `enable_scheduler: bool = False` to `create_app(...)`.
- When `enable_scheduler` is true, build the driver and run it for the life of the app using a
  FastAPI **lifespan** (`from contextlib import asynccontextmanager`; pass `lifespan=` to
  `FastAPI(...)`). In the lifespan: construct a `WorkflowResolver` over the `RegistryHolder` that
  returns the entry's `path` for a VALID workflow id and `None` otherwise —
  `holder.get(workflow_id)`; treat unknown or `problems`-with-severity-`error` as `None`. Build
  `SchedulerDeps` from the app state (`runs_dir`, `ensure_env` or the default, `popen` or the
  default, `secrets`, `budget`), then `make_scheduler_start(deps)`, then a `SchedulerDriver` on
  `application.state.schedules_path`. `driver.start()` on entry, `driver.stop()` on exit, and set
  `application.state.scheduler_driver = driver`. When `enable_scheduler` is false, do NOT set that
  attribute (tests check `getattr(app.state, "scheduler_driver", None) is None`) and you need no
  lifespan.
- Update the module-level entrypoint to `app = create_app(enable_scheduler=os.environ.get(
  "SFVF_ENABLE_SCHEDULER") == "1")` so production arms it only when the operator sets the env var.
- Keep every existing `create_app` behaviour and the existing router includes unchanged.

## Constraints / do-nots
- Touch ONLY: `app/api/runs.py`, `app/core/scheduler_runner.py` (new), `app/main.py`. Do NOT edit any
  test, `app/core/scheduler.py`, `app/core/schedules.py`, `app/core/supervisor.py`, or the frontend.
- Do NOT add a dependency (stdlib + existing modules only). Do NOT add timezone handling.
- The driver must spawn only a daemon thread; no process, no asyncio task that outlives the app.
- Keep `ruff check`, `ruff format --check`, and `mypy --strict` (`mypy sdk app`) clean; wrap ≤100 cols.

## Scope
- `app/api/runs.py`
- `app/core/scheduler_runner.py`
- `app/main.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_scheduler_runner.py tests/api/test_admit_run_dry_run.py tests/api/test_scheduler_lifespan.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
