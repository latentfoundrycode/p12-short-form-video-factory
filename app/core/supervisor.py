from __future__ import annotations

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
    del concurrency  # applied in 4b
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
        create_request(
            run_dir,
            run_id=run_id,
            workflow={"id": workflow.id, "version": workflow.version, "sdk": str(workflow.sdk)},
            params=params,
            videos=[{"index": index, "status": "running"} for index in range(1, video_count + 1)],
            atomic=workflow.atomic,
        )
        return _run_first_video(
            env.python,
            workflow_dir,
            run_dir,
            params=params,
            video_count=video_count,
            atomic=workflow.atomic,
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


def _run_first_video(
    python: Path,
    workflow_dir: Path,
    run_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    atomic: bool,
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
        shared=None,
    )
    write_json_atomic(video_dir / "context.json", context.model_dump(mode="json"))
    started = format_utc_z(utc_now())
    write_video(
        video_dir,
        VideoRecord(index=1, status="running", started_utc=started, ended_utc=None),
    )
    proc = popen(
        [
            str(python),
            "-m",
            "sfvf.runner",
            "--workflow",
            str(workflow_dir),
            "--context",
            str(video_dir / "context.json"),
        ],
        cwd=video_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_process_group_kwargs(),
    )
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
    status: RequestStatus = "complete" if proc.wait() == 0 else "failed"
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
    videos.extend(VideoRef(index=index, status="running") for index in range(2, video_count + 1))
    return update_request(
        run_dir,
        atomic=atomic,
        status=status,
        ended_utc=ended,
        videos=videos,
    )
