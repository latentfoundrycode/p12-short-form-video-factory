from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sfvf.context import ContextFile, ContextPaths

from app.core.env import EnvBlocked, EnvReady, EnvResult
from app.core.env import ensure_env as default_ensure_env
from app.core.events import to_event
from app.core.ids import allocate_run, format_utc_z, utc_now
from app.core.layout import create_run_skeleton, format_video_dir
from app.core.proc import kill_tree
from app.core.records import (
    RequestRecord,
    RequestStatus,
    VideoRecord,
    VideoRef,
    VideoStatus,
    append_event,
    create_request,
    update_request,
    write_json_atomic,
    write_video,
)
from app.paths import CACHE_DIR
from app.registry.schema import parse_manifest_toml

type EnsureEnv = Callable[..., EnvResult]
type PopenFn = Callable[..., subprocess.Popen[str]]
type RunRequestResult = EnvBlocked | RunBusy | RequestRecord

DEFAULT_SILENCE_SECONDS = 300.0
# Stage 2: graceful stop writes STOP_SENTINEL and sends the soft signal; stub
# workflows cooperate by polling the sentinel / handling the signal. The SDK's
# cooperative check-at-step-boundary and save lands in Stage 3.
STOP_SENTINEL = ".stop"

type StopMode = Literal["graceful", "hard"]
type StopResult = StopAccepted | NotRunning

_lock = threading.Lock()
_active: dict[str, str | None] = {}
_runs: dict[str, _RunState] = {}


@dataclass(frozen=True)
class RunBusy:
    workflow_id: str
    run_id: str | None = None


@dataclass(frozen=True)
class NotRunning:
    run_id: str


@dataclass(frozen=True)
class StopAccepted:
    run_id: str
    mode: StopMode


@dataclass(frozen=True)
class _ContextWiring:
    """Run-wide identity and cache values written into every context.json."""

    workflow_id: str
    run_id: str
    workflow_version: str
    video_count: int
    cache_root: Path
    workflow_dir: Path
    dry_run: bool
    step_concurrency: int


@dataclass
class _RunState:
    """Per-run lock and live video statuses. Guards events.jsonl and request.json."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    statuses: dict[int, VideoStatus] = field(default_factory=dict)
    stop_requested: bool = False
    stop_mode: StopMode | None = None
    procs: dict[str, tuple[subprocess.Popen[str], Path]] = field(default_factory=dict)

    def record_event(self, run_dir: Path, event: dict[str, Any], source: str) -> None:
        with self.lock:
            append_event(run_dir, event, source=source)

    def set_video(
        self,
        run_dir: Path,
        index: int,
        status: VideoStatus,
        *,
        atomic: bool,
    ) -> RequestRecord:
        with self.lock:
            self.statuses[index] = status
            return update_request(
                run_dir,
                atomic=atomic,
                videos=_video_refs(self.statuses),
            )

    def finish_request(
        self,
        run_dir: Path,
        *,
        atomic: bool,
        status: RequestStatus,
        ended_utc: str,
    ) -> RequestRecord:
        with self.lock:
            return update_request(
                run_dir,
                atomic=atomic,
                status=status,
                ended_utc=ended_utc,
                videos=_video_refs(self.statuses),
            )

    def register_proc(self, key: str, proc: subprocess.Popen[str], folder: Path) -> StopMode | None:
        with self.lock:
            self.procs[key] = (proc, folder)
            return self.stop_mode if self.stop_requested else None

    def unregister_proc(self, key: str) -> None:
        with self.lock:
            self.procs.pop(key, None)

    def request_stop(self, mode: StopMode) -> list[tuple[str, subprocess.Popen[str], Path]]:
        with self.lock:
            self.stop_requested = True
            self.stop_mode = mode
            return [(key, proc, folder) for key, (proc, folder) in self.procs.items()]

    def was_stopped(self) -> bool:
        with self.lock:
            return self.stop_requested

    def mark_pending_stopped(self, run_dir: Path, *, atomic: bool) -> None:
        with self.lock:
            for index, status in self.statuses.items():
                if status == "pending":
                    self.statuses[index] = "stopped"
            update_request(
                run_dir,
                atomic=atomic,
                videos=_video_refs(self.statuses),
            )


def _video_refs(statuses: dict[int, VideoStatus]) -> list[VideoRef]:
    return [VideoRef(index=index, status=statuses[index]) for index in sorted(statuses)]


def _make_context(
    wiring: _ContextWiring,
    *,
    video: Path,
    artifacts: Path,
    steps: Path,
    shared: Path,
    video_index: int,
    params: dict[str, Any],
    previous: dict[str, Any] | None = None,
    shared_payload: dict[str, Any] | None = None,
) -> ContextFile:
    return ContextFile(
        workflow_version=wiring.workflow_version,
        workflow_id=wiring.workflow_id,
        run_id=wiring.run_id,
        video_index=video_index,
        video_count=wiring.video_count,
        dry_run=wiring.dry_run,
        step_concurrency=wiring.step_concurrency,
        settings=params,
        paths=ContextPaths(
            video=video,
            artifacts=artifacts,
            steps=steps,
            shared=shared,
            cache=wiring.cache_root,
            workflow=wiring.workflow_dir,
        ),
        instructions=[],
        secrets={},
        previous=previous,
        shared=shared_payload,
    )


def _aggregate_status(
    statuses: Sequence[VideoStatus],
    *,
    atomic: bool,
    stopped: bool = False,
) -> RequestStatus:
    if stopped:
        return "stopped"
    if any(status in {"pending", "running"} for status in statuses):
        raise RuntimeError("videos remained in-flight after the pool drained")
    completed = all(status == "complete" for status in statuses)
    if atomic:
        return "complete" if completed else "failed"
    if completed:
        return "complete"
    if all(status == "failed" for status in statuses):
        return "failed"
    return "partial"


@dataclass
class _SilenceState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last_activity: float = field(default_factory=time.monotonic)
    current_family: str | None = None
    gate_open: bool = False

    def note(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.last_activity = time.monotonic()
            kind = event.get("t")
            if self.gate_open and kind != "gate":
                self.gate_open = False
            if kind == "step":
                name = event.get("name")
                if isinstance(name, str):
                    self.current_family = name
            elif kind == "gate":
                self.gate_open = True


def _family_limit(family: str | None, limits: dict[str, float], default: float) -> float:
    if family is not None and family in limits:
        return limits[family]
    return default


def _watchdog_interval(limit: float) -> float:
    return min(0.25, max(0.05, limit / 4.0))


def run_request(
    workflow_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    concurrency: int,
    runs_dir: Path | None = None,
    ensure_env: EnsureEnv = default_ensure_env,
    popen: PopenFn = subprocess.Popen,
    silence_limit_default: float = DEFAULT_SILENCE_SECONDS,
    on_started: Callable[[str], None] | None = None,
    cache_dir: Path | None = None,
    dry_run: bool = False,
    step_concurrency: int = 1,
) -> RunRequestResult:
    workflow_dir = workflow_dir.resolve()
    manifest = parse_manifest_toml((workflow_dir / "workflow.toml").read_text(encoding="utf-8"))
    workflow = manifest.workflow
    workflow_id = workflow.id

    with _lock:
        if workflow_id in _active:
            return RunBusy(workflow_id=workflow_id, run_id=_active[workflow_id])
        _active[workflow_id] = None
    run_id: str | None = None
    try:
        env = ensure_env(workflow_id, workflow_dir, workflow.python)
        if isinstance(env, EnvBlocked):
            return env
        if not isinstance(env, EnvReady):
            raise TypeError("ensure_env must return EnvReady or EnvBlocked")
        run_id, run_dir = allocate_run(workflow_id, runs_dir=runs_dir)
        mode = "dry" if dry_run else "real"
        cache_root = ((cache_dir or CACHE_DIR) / workflow_id / mode).resolve()
        cache_root.mkdir(parents=True, exist_ok=True)
        wiring = _ContextWiring(
            workflow_id=workflow_id,
            run_id=run_id,
            workflow_version=workflow.version,
            video_count=video_count,
            cache_root=cache_root,
            workflow_dir=workflow_dir,
            dry_run=dry_run,
            step_concurrency=step_concurrency,
        )
        with _lock:
            _active[workflow_id] = run_id
        create_run_skeleton(run_dir, video_count)
        state = _RunState(
            statuses=dict.fromkeys(range(1, video_count + 1), "pending"),
        )
        with _lock:
            _runs[run_id] = state
        create_request(
            run_dir,
            run_id=run_id,
            workflow={"id": workflow.id, "version": workflow.version, "sdk": str(workflow.sdk)},
            params=params,
            videos=_video_refs(state.statuses),
            atomic=workflow.atomic,
        )
        if on_started is not None:
            on_started(run_id)
        shared: dict[str, Any] | None = None
        limits = {item.step: float(item.seconds) for item in manifest.limits}
        if workflow.prepare:
            ok, shared = _run_prepare(
                env.python,
                workflow_dir,
                run_dir,
                params=params,
                popen=popen,
                state=state,
                limits=limits,
                silence_limit_default=silence_limit_default,
                wiring=wiring,
            )
            if not ok:
                if state.was_stopped():
                    state.mark_pending_stopped(run_dir, atomic=workflow.atomic)
                    return state.finish_request(
                        run_dir,
                        atomic=workflow.atomic,
                        status="stopped",
                        ended_utc=format_utc_z(utc_now()),
                    )
                return state.finish_request(
                    run_dir,
                    atomic=workflow.atomic,
                    status="failed",
                    ended_utc=format_utc_z(utc_now()),
                )
            if state.was_stopped():
                state.mark_pending_stopped(run_dir, atomic=workflow.atomic)
                return state.finish_request(
                    run_dir,
                    atomic=workflow.atomic,
                    status="stopped",
                    ended_utc=format_utc_z(utc_now()),
                )
        return _run_videos(
            env.python,
            workflow_dir,
            run_dir,
            params=params,
            video_count=video_count,
            concurrency=concurrency,
            atomic=workflow.atomic,
            shared=shared,
            popen=popen,
            state=state,
            limits=limits,
            silence_limit_default=silence_limit_default,
            wiring=wiring,
        )
    finally:
        with _lock:
            held = _active.get(workflow_id)
            if held is None or held == run_id:
                _active.pop(workflow_id, None)
            if run_id is not None:
                _runs.pop(run_id, None)


def _process_group_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _send_soft_signal(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return


def _apply_stop(mode: StopMode, proc: subprocess.Popen[str], folder: Path) -> None:
    if mode == "graceful":
        (folder / STOP_SENTINEL).touch()
        _send_soft_signal(proc)
    else:
        kill_tree(proc)


def stop(run_id: str, *, mode: StopMode) -> StopResult:
    if mode not in {"graceful", "hard"}:
        raise ValueError(f"unknown stop mode: {mode}")
    with _lock:
        state = _runs.get(run_id)
    if state is None:
        return NotRunning(run_id=run_id)
    snapshot = state.request_stop(mode)
    for _key, proc, folder in snapshot:
        _apply_stop(mode, proc, folder)
    return StopAccepted(run_id=run_id, mode=mode)


def _start_runner(
    python: Path,
    workflow_dir: Path,
    context_path: Path,
    *,
    cwd: Path,
    popen: PopenFn,
    extra_args: list[str] | None = None,
) -> subprocess.Popen[str]:
    command = [
        str(python),
        "-m",
        "sfvf.runner",
        "--workflow",
        str(workflow_dir),
        "--context",
        str(context_path),
    ]
    if extra_args:
        command.extend(extra_args)
    return popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        # Stage-2 workflows are single-threaded so stdout/stderr don't interleave mid-line;
        # revisit (separate pipes) if Stage-3 in-video concurrency ever corrupts a line.
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_process_group_kwargs(),
    )


def _watch_silence(
    proc: subprocess.Popen[str],
    silence: _SilenceState,
    *,
    limits: dict[str, float],
    default: float,
    state: _RunState,
    run_dir: Path,
    source: str,
    stop: threading.Event,
) -> None:
    while not stop.wait(
        timeout=_watchdog_interval(_family_limit(silence.current_family, limits, default))
    ):
        family = "unknown"
        limit = default
        with silence.lock:
            if proc.poll() is not None:
                return
            if silence.gate_open:
                continue
            family = silence.current_family or "unknown"
            limit = _family_limit(silence.current_family, limits, default)
            if time.monotonic() - silence.last_activity <= limit:
                continue
            if proc.poll() is not None:
                return
        state.record_event(
            run_dir,
            {
                "t": "log",
                "level": "error",
                "msg": f"step '{family}' silent past {limit:g}s limit; killed",
            },
            source,
        )
        if proc.poll() is None:
            kill_tree(proc)
        return


def _consume_stdout(
    proc: subprocess.Popen[str],
    run_dir: Path,
    source: str,
    *,
    state: _RunState,
    silence: _SilenceState,
    limits: dict[str, float],
    silence_limit_default: float,
) -> dict[str, Any] | None:
    captured: dict[str, Any] | None = None
    if proc.stdout is None:
        raise RuntimeError("runner stdout was not piped")
    stop = threading.Event()
    watcher = threading.Thread(
        target=_watch_silence,
        kwargs={
            "proc": proc,
            "silence": silence,
            "limits": limits,
            "default": silence_limit_default,
            "state": state,
            "run_dir": run_dir,
            "source": source,
            "stop": stop,
        },
        name=f"sfvf-silence-{source}",
        daemon=True,
    )
    watcher.start()
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\r\n")
            if not line:
                continue
            event = to_event(line)
            silence.note(event)
            state.record_event(run_dir, event, source)
            if event.get("t") == "result":
                captured = {key: value for key, value in event.items() if key != "t"}
    finally:
        stop.set()
        watcher.join(timeout=1)
    return captured


def _run_prepare(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    params: dict[str, Any],
    popen: PopenFn,
    state: _RunState,
    limits: dict[str, float],
    silence_limit_default: float,
    wiring: _ContextWiring,
) -> tuple[bool, dict[str, Any] | None]:
    shared_dir = (run_dir / "shared").resolve()
    artifacts = shared_dir / "artifacts"
    steps = shared_dir / ".steps"
    artifacts.mkdir(parents=True, exist_ok=True)
    steps.mkdir(exist_ok=True)
    context_path = shared_dir / "context.json"
    result_path = shared_dir / "result.json"
    context = _make_context(
        wiring,
        video=shared_dir,
        artifacts=artifacts,
        steps=steps,
        shared=shared_dir,
        video_index=0,
        params=params,
    )
    write_json_atomic(context_path, context.model_dump(mode="json"))
    proc = _start_runner(
        python,
        workflow_dir,
        context_path,
        cwd=shared_dir,
        popen=popen,
        extra_args=["--entry", "prepare", "--result", str(result_path)],
    )
    pending = state.register_proc("prep", proc, shared_dir)
    if pending is not None:
        _apply_stop(pending, proc, shared_dir)
    try:
        _consume_stdout(
            proc,
            run_dir,
            "prep",
            state=state,
            silence=_SilenceState(),
            limits=limits,
            silence_limit_default=silence_limit_default,
        )
        if proc.wait() != 0 or not result_path.is_file():
            return False, None
    finally:
        state.unregister_proc("prep")
    payload: object = json.loads(result_path.read_text(encoding="utf-8"))
    if payload is None:
        return True, None
    if not isinstance(payload, dict):
        return False, None
    return True, payload


def _run_videos(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    concurrency: int,
    atomic: bool,
    shared: dict[str, Any] | None,
    popen: PopenFn,
    state: _RunState,
    limits: dict[str, float],
    silence_limit_default: float,
    wiring: _ContextWiring,
) -> RequestRecord:
    workers = max(1, concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _run_one_video,
                python,
                workflow_dir,
                run_dir,
                index=index,
                video_count=video_count,
                params=params,
                atomic=atomic,
                shared=shared,
                popen=popen,
                state=state,
                limits=limits,
                silence_limit_default=silence_limit_default,
                wiring=wiring,
            )
            for index in range(1, video_count + 1)
        ]
        for future in as_completed(futures):
            future.result()
    return state.finish_request(
        run_dir,
        atomic=atomic,
        status=_aggregate_status(
            list(state.statuses.values()),
            atomic=atomic,
            stopped=state.was_stopped(),
        ),
        ended_utc=format_utc_z(utc_now()),
    )


def _run_one_video(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    index: int,
    video_count: int,
    params: dict[str, Any],
    atomic: bool,
    shared: dict[str, Any] | None,
    popen: PopenFn,
    state: _RunState,
    limits: dict[str, float],
    silence_limit_default: float,
    wiring: _ContextWiring,
) -> None:
    source = format_video_dir(index, video_count)
    video_dir = (run_dir / source).resolve()
    with state.lock:
        if state.stop_requested:
            state.statuses[index] = "stopped"
            update_request(
                run_dir,
                atomic=atomic,
                videos=_video_refs(state.statuses),
            )
            return
    started: str | None = None
    try:
        context = _make_context(
            wiring,
            video=video_dir,
            artifacts=(video_dir / "artifacts").resolve(),
            steps=(video_dir / ".steps").resolve(),
            shared=(run_dir / "shared").resolve(),
            video_index=index,
            params=params,
            shared_payload=shared,
        )
        write_json_atomic(video_dir / "context.json", context.model_dump(mode="json"))
        started = format_utc_z(utc_now())
        state.set_video(run_dir, index, "running", atomic=atomic)
        write_video(
            video_dir,
            VideoRecord(index=index, status="running", started_utc=started, ended_utc=None),
        )
        proc = _start_runner(
            python,
            workflow_dir,
            video_dir / "context.json",
            cwd=video_dir,
            popen=popen,
        )
        pending = state.register_proc(source, proc, video_dir)
        if pending is not None:
            _apply_stop(pending, proc, video_dir)
        try:
            captured = _consume_stdout(
                proc,
                run_dir,
                source,
                state=state,
                silence=_SilenceState(),
                limits=limits,
                silence_limit_default=silence_limit_default,
            )
            returncode = proc.wait()
        finally:
            state.unregister_proc(source)
        status: VideoStatus = (
            "stopped" if state.was_stopped() else ("complete" if returncode == 0 else "failed")
        )
        ended = format_utc_z(utc_now())
        write_video(
            video_dir,
            VideoRecord(
                index=index,
                status=status,
                started_utc=started,
                ended_utc=ended,
                result=captured if status == "complete" else None,
            ),
        )
        state.set_video(run_dir, index, status, atomic=atomic)
    except Exception:
        ended = format_utc_z(utc_now())
        status = "stopped" if state.was_stopped() else "failed"
        if started is not None:
            write_video(
                video_dir,
                VideoRecord(
                    index=index,
                    status=status,
                    started_utc=started,
                    ended_utc=ended,
                ),
            )
        state.set_video(run_dir, index, status, atomic=atomic)
