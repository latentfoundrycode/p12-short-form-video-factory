from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sfvf.context import BudgetConfig

from app.api.runs import AdmissionResult, admit_run
from app.core.env import ensure_env as default_ensure_env
from app.core.scheduler import DEFAULT_GRACE, SchedulerState, StartFn, TickResult, tick
from app.core.schedules import ScheduleEntry
from app.core.supervisor import EnsureEnv, PopenFn

type WorkflowResolver = Callable[[str], Path | None]


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
    admit: Callable[..., AdmissionResult] = admit_run


def make_scheduler_start(deps: SchedulerDeps) -> StartFn:
    def start(entry: ScheduleEntry, dry_run: bool) -> object:
        workflow_dir = deps.resolve_workflow(entry.workflow_id)
        if workflow_dir is None:
            return SkippedUnknownWorkflow(entry.workflow_id)
        return deps.admit(
            workflow_dir,
            params=entry.params,
            video_count=entry.video_count,
            concurrency=entry.concurrency,
            dry_run=dry_run,
            runs_dir=deps.runs_dir,
            ensure_env=deps.ensure_env,
            popen=deps.popen,
            secrets=deps.secrets,
            budget=deps.budget,
        )

    return start


class SchedulerDriver:
    def __init__(
        self,
        *,
        schedules_path: Path,
        start: StartFn,
        now: Callable[[], datetime] = datetime.now,
        interval: float = 60.0,
        grace: timedelta = DEFAULT_GRACE,
        state: SchedulerState | None = None,
    ) -> None:
        self._schedules_path = schedules_path
        self._start = start
        self._now = now
        self._interval = interval
        self._grace = grace
        self._state = state if state is not None else SchedulerState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def tick_once(self) -> list[TickResult]:
        return tick(
            self._now(),
            schedules_path=self._schedules_path,
            state=self._state,
            start=self._start,
            grace=self._grace,
        )

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="sfvf-scheduler",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is None:
                return
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        self.tick_once()
        while not self._stop.wait(self._interval):
            self.tick_once()
