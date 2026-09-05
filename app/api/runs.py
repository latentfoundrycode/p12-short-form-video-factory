from __future__ import annotations

import asyncio
import json
import mimetypes
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sfvf.context import BudgetConfig

from app.api.workflows import RegistryHolder
from app.core.env import EnvBlocked
from app.core.env import ensure_env as default_ensure_env
from app.core.layout import format_video_dir
from app.core.records import (
    RequestRecord,
    RequestStatus,
    VideoRecord,
    VideoRef,
    VideoStatus,
    WorkflowRef,
    read_events,
    read_request,
    read_video,
)
from app.core.supervisor import (
    EnsureEnv,
    NotRunning,
    PopenFn,
    RunBusy,
    RunRequestResult,
    StopAccepted,
    StopMode,
    run_request,
    stop,
)
from app.paths import RUNS_DIR, is_safe_path_segment, safe_join
from app.registry.validate import WorkflowEntry

router = APIRouter(prefix="/api")

_TERMINAL_STATUSES = frozenset({"complete", "partial", "stopped", "stopped-budget", "failed"})
_REQUEST_WAIT_SECONDS = 2.0
_REQUEST_POLL_SECONDS = 0.05
_LIVE_POLL_SECONDS = 0.25

# Known limitation: POST /runs admission waits through ensure_env (venv setup).
# An existing venv is fast; a first-time build makes the response slow. Env setup
# is intentionally still synchronous for this increment.


@dataclass(frozen=True)
class AdmissionAccepted:
    run_id: str


@dataclass(frozen=True)
class AdmissionBusy:
    workflow_id: str


@dataclass(frozen=True)
class AdmissionBlocked:
    reason: str


type AdmissionResult = AdmissionAccepted | AdmissionBusy | AdmissionBlocked


class LaunchBody(BaseModel):
    params: dict[str, Any]
    video_count: int = Field(ge=1)
    concurrency: int = Field(ge=1)


class LaunchAcceptedOut(BaseModel):
    run_id: str


class EnvBlockedOut(BaseModel):
    reason: str


class StopBody(BaseModel):
    mode: StopMode


class StopOut(BaseModel):
    run_id: str
    mode: StopMode


class VideoRefOut(BaseModel):
    index: int
    status: VideoStatus


class RunSummaryOut(BaseModel):
    run_id: str
    status: RequestStatus
    started_utc: str
    ended_utc: str | None
    videos: list[VideoRefOut]


class RunListOut(BaseModel):
    runs: list[RunSummaryOut]


class RunDetailOut(BaseModel):
    run_id: str
    workflow: WorkflowRef
    started_utc: str
    ended_utc: str | None
    status: RequestStatus
    params: dict[str, Any]
    params_locked_utc: str
    videos: list[VideoRef]
    video_records: list[VideoRecord]
    budget: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None


def _holder(request: Request) -> RegistryHolder:
    return cast(RegistryHolder, request.app.state.registry)


def _runs_dir(request: Request) -> Path:
    return cast(Path, getattr(request.app.state, "runs_dir", RUNS_DIR))


def _ensure_env(request: Request) -> EnsureEnv:
    injected = getattr(request.app.state, "ensure_env", None)
    return cast(EnsureEnv, injected) if injected is not None else default_ensure_env


def _popen(request: Request) -> PopenFn:
    injected = getattr(request.app.state, "popen", None)
    return cast(PopenFn, injected) if injected is not None else subprocess.Popen


def _secrets(request: Request) -> Mapping[str, str]:
    injected = getattr(request.app.state, "secrets", None)
    return cast(Mapping[str, str], injected) if injected is not None else {}


def _budget(request: Request) -> BudgetConfig | None:
    return getattr(request.app.state, "budget", None)


def admit_run(
    workflow_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    concurrency: int,
    runs_dir: Path,
    ensure_env: EnsureEnv = default_ensure_env,
    popen: PopenFn = subprocess.Popen,
    secrets: Mapping[str, str] | None = None,
    budget: BudgetConfig | None = None,
) -> AdmissionResult:
    """Launch run_request on a daemon thread; return as soon as admission resolves."""
    started = threading.Event()
    run_ids: list[str] = []
    results: list[RunRequestResult] = []
    errors: list[BaseException] = []

    def on_started(run_id: str) -> None:
        run_ids.append(run_id)
        started.set()

    def target() -> None:
        try:
            results.append(
                run_request(
                    workflow_dir,
                    params=params,
                    video_count=video_count,
                    concurrency=concurrency,
                    runs_dir=runs_dir,
                    ensure_env=ensure_env,
                    popen=popen,
                    on_started=on_started,
                    secrets=secrets,
                    budget=budget,
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            started.set()

    thread = threading.Thread(target=target, name="sfvf-run", daemon=True)
    thread.start()
    started.wait()

    if run_ids:
        return AdmissionAccepted(run_id=run_ids[0])

    thread.join(timeout=5)
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("run thread exited without a result")
    result = results[0]
    if isinstance(result, RunBusy):
        return AdmissionBusy(workflow_id=result.workflow_id)
    if isinstance(result, EnvBlocked):
        return AdmissionBlocked(reason=result.reason)
    return AdmissionAccepted(run_id=result.run_id)


def _require_workflow(request: Request, workflow_id: str) -> WorkflowEntry:
    if not is_safe_path_segment(workflow_id):
        raise HTTPException(status_code=404)
    entry = _holder(request).get(workflow_id)
    if entry is None:
        raise HTTPException(status_code=404)
    return entry


def _summary(record: RequestRecord) -> RunSummaryOut:
    return RunSummaryOut(
        run_id=record.run_id,
        status=record.status,
        started_utc=record.started_utc,
        ended_utc=record.ended_utc,
        videos=[VideoRefOut(index=video.index, status=video.status) for video in record.videos],
    )


def _detail(run_dir: Path, record: RequestRecord) -> RunDetailOut:
    video_records: list[VideoRecord] = []
    for video in record.videos:
        folder = run_dir / format_video_dir(video.index, len(record.videos))
        if (folder / "video.json").is_file():
            video_records.append(read_video(folder))
    return RunDetailOut(
        run_id=record.run_id,
        workflow=record.workflow,
        started_utc=record.started_utc,
        ended_utc=record.ended_utc,
        status=record.status,
        params=record.params,
        params_locked_utc=record.params_locked_utc,
        videos=record.videos,
        video_records=video_records,
        budget=record.budget,
        forecast=record.forecast,
    )


@router.post("/workflows/{workflow_id}/runs")
def launch_run(workflow_id: str, body: LaunchBody, request: Request) -> JSONResponse:
    entry = _require_workflow(request, workflow_id)
    if any(problem.severity == "error" for problem in entry.problems):
        raise HTTPException(status_code=422, detail="workflow is invalid")
    outcome = admit_run(
        entry.path,
        params=body.params,
        video_count=body.video_count,
        concurrency=body.concurrency,
        runs_dir=_runs_dir(request),
        ensure_env=_ensure_env(request),
        popen=_popen(request),
        secrets=_secrets(request),
        budget=_budget(request),
    )
    if isinstance(outcome, AdmissionAccepted):
        return JSONResponse(
            status_code=202,
            content=LaunchAcceptedOut(run_id=outcome.run_id).model_dump(),
        )
    if isinstance(outcome, AdmissionBusy):
        return JSONResponse(
            status_code=409,
            content={"detail": "workflow already has an active run"},
        )
    return JSONResponse(
        status_code=422,
        content=EnvBlockedOut(reason=outcome.reason).model_dump(),
    )


@router.post("/workflows/{workflow_id}/runs/{run_id}/stop", response_model=StopOut)
def stop_run(workflow_id: str, run_id: str, body: StopBody, request: Request) -> StopOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    result = stop(run_id, mode=body.mode)
    if isinstance(result, NotRunning):
        raise HTTPException(status_code=404)
    if not isinstance(result, StopAccepted):
        raise HTTPException(status_code=404)
    return StopOut(run_id=result.run_id, mode=result.mode)


@router.get("/workflows/{workflow_id}/runs", response_model=RunListOut)
def list_runs(workflow_id: str, request: Request) -> RunListOut:
    _require_workflow(request, workflow_id)
    root = _runs_dir(request) / workflow_id
    if not root.is_dir():
        return RunListOut(runs=[])
    summaries: list[RunSummaryOut] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if not (child / "request.json").is_file():
            continue
        summaries.append(_summary(read_request(child)))
    summaries.sort(key=lambda item: item.run_id, reverse=True)
    return RunListOut(runs=summaries)


@router.get("/workflows/{workflow_id}/runs/{run_id}", response_model=RunDetailOut)
def get_run(workflow_id: str, run_id: str, request: Request) -> RunDetailOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not (run_dir / "request.json").is_file():
        raise HTTPException(status_code=404)
    return _detail(run_dir, read_request(run_dir))


def _sse_data_line(ts: str, source: str, event: dict[str, Any]) -> str:
    envelope = {"ts": ts, "source": source, "event": event}
    return f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"


async def _sse_event_stream(request: Request, run_dir: Path) -> AsyncIterator[str]:
    emitted = 0
    while True:
        if await request.is_disconnected():
            return

        events = list(read_events(run_dir))
        for ts, source, event in events[emitted:]:
            yield _sse_data_line(ts, source, event)
            emitted += 1

        if read_request(run_dir).status in _TERMINAL_STATUSES:
            events = list(read_events(run_dir))
            for ts, source, event in events[emitted:]:
                yield _sse_data_line(ts, source, event)
                emitted += 1
            return

        await asyncio.sleep(_LIVE_POLL_SECONDS)


@router.get("/workflows/{workflow_id}/runs/{run_id}/events")
async def stream_run_events(workflow_id: str, run_id: str, request: Request) -> StreamingResponse:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    request_path = run_dir / "request.json"
    deadline = time.monotonic() + _REQUEST_WAIT_SECONDS
    while not request_path.is_file():
        if time.monotonic() >= deadline:
            raise HTTPException(status_code=404)
        await asyncio.sleep(_REQUEST_POLL_SECONDS)
    return StreamingResponse(
        _sse_event_stream(request, run_dir),
        media_type="text/event-stream",
    )


@router.get("/workflows/{workflow_id}/runs/{run_id}/files/{path:path}")
def get_run_file(workflow_id: str, run_id: str, path: str, request: Request) -> FileResponse:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404)
    target = safe_join(run_dir, path)
    if target is None:
        raise HTTPException(status_code=404)
    resolved = target.resolve()
    if not resolved.is_relative_to(run_dir.resolve()):
        raise HTTPException(status_code=404)
    if not resolved.is_file():
        raise HTTPException(status_code=404)
    if resolved.name == "context.json":
        raise HTTPException(status_code=404)
    media_type, _encoding = mimetypes.guess_type(resolved.name)
    return FileResponse(resolved, media_type=media_type or "application/octet-stream")
