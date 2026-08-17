from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sfvf.context import ContextFile, ContextPaths

from app.core.env import EnvBlocked, EnvReady, EnvResult
from app.core.env import ensure_env as default_ensure_env
from app.core.events import to_event
from app.core.ids import allocate_run, format_utc_z, utc_now
from app.core.layout import create_run_skeleton, format_video_dir
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
from app.registry.schema import parse_manifest_toml

type EnsureEnv = Callable[..., EnvResult]
type PopenFn = Callable[..., subprocess.Popen[str]]
type RunRequestResult = EnvBlocked | RunBusy | RequestRecord

_lock = threading.Lock()
_active: dict[str, str | None] = {}


@dataclass(frozen=True)
class RunBusy:
    workflow_id: str
    run_id: str | None = None


def run_request(
    workflow_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    concurrency: int,
    runs_dir: Path | None = None,
    ensure_env: EnsureEnv = default_ensure_env,
    popen: PopenFn = subprocess.Popen,
) -> RunRequestResult:
    del concurrency  # applied in commit 2
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
        with _lock:
            _active[workflow_id] = run_id
        create_run_skeleton(run_dir, video_count)
        pending = [VideoRef(index=index, status="pending") for index in range(1, video_count + 1)]
        create_request(
            run_dir,
            run_id=run_id,
            workflow={"id": workflow.id, "version": workflow.version, "sdk": str(workflow.sdk)},
            params=params,
            videos=pending,
            atomic=workflow.atomic,
        )
        shared: dict[str, Any] | None = None
        if workflow.prepare:
            ok, shared = _run_prepare(
                env.python,
                workflow_dir,
                run_dir,
                params=params,
                popen=popen,
            )
            if not ok:
                ended = format_utc_z(utc_now())
                return update_request(
                    run_dir,
                    atomic=workflow.atomic,
                    status="failed",
                    ended_utc=ended,
                    videos=pending,
                )
        return _run_first_video(
            env.python,
            workflow_dir,
            run_dir,
            params=params,
            video_count=video_count,
            atomic=workflow.atomic,
            shared=shared,
            popen=popen,
        )
    finally:
        with _lock:
            held = _active.get(workflow_id)
            if held is None or held == run_id:
                _active.pop(workflow_id, None)


def _process_group_kwargs() -> dict[str, Any]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


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


def _consume_stdout(
    proc: subprocess.Popen[str], run_dir: Path, source: str
) -> dict[str, Any] | None:
    captured: dict[str, Any] | None = None
    if proc.stdout is None:
        raise RuntimeError("runner stdout was not piped")
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        event = to_event(line)
        append_event(run_dir, event, source=source)
        if event.get("t") == "result":
            captured = {key: event[key] for key in ("video", "caption") if key in event}
    return captured


def _run_prepare(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    params: dict[str, Any],
    popen: PopenFn,
) -> tuple[bool, dict[str, Any] | None]:
    shared_dir = (run_dir / "shared").resolve()
    artifacts = shared_dir / "artifacts"
    steps = shared_dir / ".steps"
    artifacts.mkdir(parents=True, exist_ok=True)
    steps.mkdir(exist_ok=True)
    context_path = shared_dir / "context.json"
    result_path = shared_dir / "result.json"
    context = ContextFile(
        settings=params,
        paths=ContextPaths(
            video=shared_dir,
            artifacts=artifacts,
            steps=steps,
            shared=shared_dir,
        ),
        instructions=[],
        secrets={},
        previous=None,
        shared=None,
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
    _consume_stdout(proc, run_dir, "prep")
    if proc.wait() != 0 or not result_path.is_file():
        return False, None
    payload: object = json.loads(result_path.read_text(encoding="utf-8"))
    if payload is None:
        return True, None
    if not isinstance(payload, dict):
        return False, None
    return True, payload


def _run_first_video(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    atomic: bool,
    shared: dict[str, Any] | None,
    popen: PopenFn,
) -> RequestRecord:
    source = format_video_dir(1, video_count)
    video_dir = (run_dir / source).resolve()
    context = ContextFile(
        settings=params,
        paths=ContextPaths(
            video=video_dir,
            artifacts=(video_dir / "artifacts").resolve(),
            steps=(video_dir / ".steps").resolve(),
            shared=(run_dir / "shared").resolve(),
        ),
        instructions=[],
        secrets={},
        previous=None,
        shared=shared,
    )
    write_json_atomic(video_dir / "context.json", context.model_dump(mode="json"))
    started = format_utc_z(utc_now())
    videos_running = [VideoRef(index=1, status="running")]
    videos_running.extend(
        VideoRef(index=index, status="pending") for index in range(2, video_count + 1)
    )
    update_request(run_dir, atomic=atomic, videos=videos_running)
    write_video(
        video_dir,
        VideoRecord(index=1, status="running", started_utc=started, ended_utc=None),
    )
    proc = _start_runner(
        python,
        workflow_dir,
        video_dir / "context.json",
        cwd=video_dir,
        popen=popen,
    )
    captured = _consume_stdout(proc, run_dir, source)
    status: VideoStatus = "complete" if proc.wait() == 0 else "failed"
    ended = format_utc_z(utc_now())
    write_video(
        video_dir,
        VideoRecord(
            index=1,
            status=status,
            started_utc=started,
            ended_utc=ended,
            result=captured if status == "complete" else None,
        ),
    )
    videos = [VideoRef(index=1, status=status)]
    videos.extend(VideoRef(index=index, status="pending") for index in range(2, video_count + 1))
    request_status: RequestStatus = "complete" if status == "complete" else "failed"
    return update_request(
        run_dir,
        atomic=atomic,
        status=request_status,
        ended_utc=ended,
        videos=videos,
    )
