from __future__ import annotations

import asyncio
import json
import mimetypes
import shutil
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
from sfvf.providers import UnknownModelError, provider_configured, resolve

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
    write_json_atomic,
)
from app.core.supervisor import (
    EnsureEnv,
    NotRunning,
    PopenFn,
    RunBusy,
    RunRequestResult,
    StopAccepted,
    StopMode,
    _redact_secrets,
    run_request,
    stop,
)
from app.paths import RUNS_DIR, is_safe_path_segment, safe_join
from app.registry.validate import WorkflowEntry

router = APIRouter(prefix="/api")

_TERMINAL_STATUSES = frozenset({"complete", "partial", "stopped", "stopped-budget", "failed"})
_CLEARABLE = frozenset({"failed", "stopped", "stopped-budget"})
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


class DeleteRunOut(BaseModel):
    deleted: str


class ClearFailedOut(BaseModel):
    deleted: list[str]


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


class RunFileOut(BaseModel):
    path: str
    size: int


class RunFilesOut(BaseModel):
    files: list[RunFileOut]


class PendingGateOut(BaseModel):
    video: str
    video_index: int
    token: str
    family: str
    shape: str
    prompt: str
    payload: Any | None = None
    options: list[Any] | None = None
    items: list[Any] | None = None
    on_bypass: str | None = None


class GatesOut(BaseModel):
    gates: list[PendingGateOut]


class SubmitGateIn(BaseModel):
    video: str
    token: str
    decision: dict[str, Any]


class SubmitGateOut(BaseModel):
    ok: bool


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


def _disabled_web_tiers(request: Request) -> list[str]:
    return list(getattr(request.app.state, "disabled_web_tiers", None) or [])


def _unconfigured_model_param(
    entry: WorkflowEntry, params: dict[str, Any], configured: set[str]
) -> str | None:
    """Return a refusal message if a model-source param names a model whose provider is
    unconfigured.

    A "model param" is one whose options_from is a models source (sfvf.models[:kind] or
    <provider>.models). An unknown / non-string / absent value is not this check's concern
    (skipped).
    """
    manifest = entry.manifest
    if manifest is None:
        return None
    for param in manifest.params:
        source = param.options_from
        is_model_source = source is not None and (
            source == "sfvf.models"
            or source.startswith("sfvf.models:")
            or source.endswith(".models")
        )
        if not is_model_source:
            continue
        value = params.get(param.key)
        if not isinstance(value, str):
            continue
        try:
            provider, _model = resolve(value)
        except UnknownModelError:
            continue
        if not provider_configured(provider, configured):
            return f"model {value!r} requires provider {provider.label!r}, which is not configured"
    return None


def admit_run(
    workflow_dir: Path,
    *,
    params: dict[str, Any],
    video_count: int,
    concurrency: int,
    dry_run: bool = False,
    gates_auto: bool = False,
    runs_dir: Path,
    ensure_env: EnsureEnv = default_ensure_env,
    popen: PopenFn = subprocess.Popen,
    secrets: Mapping[str, str] | None = None,
    budget: BudgetConfig | None = None,
    disabled_web_tiers: list[str] | None = None,
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
                    dry_run=dry_run,
                    gates_auto=gates_auto,
                    on_started=on_started,
                    secrets=secrets,
                    budget=budget,
                    disabled_web_tiers=disabled_web_tiers or [],
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


def _is_well_formed_gate_event(source: object, event: object) -> bool:
    return (
        isinstance(source, str)
        and isinstance(event, dict)
        and event.get("t") == "gate"
        and all(
            isinstance(event.get(field), str) for field in ("token", "family", "shape", "prompt")
        )
    )


@router.post("/workflows/{workflow_id}/runs")
def launch_run(workflow_id: str, body: LaunchBody, request: Request) -> JSONResponse:
    entry = _require_workflow(request, workflow_id)
    if any(problem.severity == "error" for problem in entry.problems):
        raise HTTPException(status_code=422, detail="workflow is invalid")
    blocked = _unconfigured_model_param(entry, body.params, set(_secrets(request)))
    if blocked is not None:
        raise HTTPException(status_code=422, detail=blocked)
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
        disabled_web_tiers=_disabled_web_tiers(request),
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


@router.delete("/workflows/{workflow_id}/runs/clear-failed", response_model=ClearFailedOut)
def clear_failed_runs(workflow_id: str, request: Request) -> ClearFailedOut:
    _require_workflow(request, workflow_id)
    root = _runs_dir(request) / workflow_id
    if not root.is_dir():
        return ClearFailedOut(deleted=[])
    deleted: list[str] = []
    root_resolved = root.resolve()
    for child in root.iterdir():
        if not child.is_dir() or not (child / "request.json").is_file():
            continue
        try:
            record = read_request(child)
        except (OSError, ValueError):
            continue
        if record.status not in _CLEARABLE:
            continue
        if child.resolve() != root_resolved / child.name:
            continue
        try:
            shutil.rmtree(child)
        except OSError:
            continue
        deleted.append(child.name)
    return ClearFailedOut(deleted=sorted(deleted))


@router.delete("/workflows/{workflow_id}/runs/{run_id}", response_model=DeleteRunOut)
def delete_run(workflow_id: str, run_id: str, request: Request) -> DeleteRunOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    expected = (_runs_dir(request) / workflow_id).resolve() / run_id
    if run_dir.resolve() != expected:
        raise HTTPException(status_code=404)
    if not (run_dir / "request.json").is_file():
        raise HTTPException(status_code=404)
    if read_request(run_dir).status == "running":
        raise HTTPException(status_code=409, detail="run is still active")
    resolved = run_dir.resolve()
    try:
        shutil.rmtree(resolved)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="could not delete run") from exc
    return DeleteRunOut(deleted=run_id)


@router.get("/workflows/{workflow_id}/runs/{run_id}", response_model=RunDetailOut)
def get_run(workflow_id: str, run_id: str, request: Request) -> RunDetailOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not (run_dir / "request.json").is_file():
        raise HTTPException(status_code=404)
    return _detail(run_dir, read_request(run_dir))


@router.get("/workflows/{workflow_id}/runs/{run_id}/gates", response_model=GatesOut)
def list_pending_gates(workflow_id: str, run_id: str, request: Request) -> GatesOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not (run_dir / "request.json").is_file():
        raise HTTPException(status_code=404)

    pending: dict[tuple[str, str], PendingGateOut] = {}
    order: list[tuple[str, str]] = []
    for _ts, source, event in read_events(run_dir):
        if not _is_well_formed_gate_event(source, event):
            continue
        token = event.get("token")
        family = event.get("family")
        shape = event.get("shape")
        prompt = event.get("prompt")
        if (
            not isinstance(token, str)
            or not isinstance(family, str)
            or not isinstance(shape, str)
            or not isinstance(prompt, str)
        ):
            continue
        options = event.get("options")
        items = event.get("items")
        on_bypass = event.get("on_bypass")
        if (
            (options is not None and not isinstance(options, list))
            or (items is not None and not isinstance(items, list))
            or (on_bypass is not None and not isinstance(on_bypass, str))
        ):
            continue
        if (run_dir / source / "gates" / f"{token}.json").exists():
            continue
        key = (source, token)
        if key not in pending:
            order.append(key)
        pending[key] = PendingGateOut(
            video=source,
            video_index=int(source) if source.isdigit() else 0,
            token=token,
            family=family,
            shape=shape,
            prompt=prompt,
            payload=event.get("payload"),
            options=options,
            items=items,
            on_bypass=on_bypass,
        )
    return GatesOut(gates=[pending[key] for key in order])


@router.post("/workflows/{workflow_id}/runs/{run_id}/gates", response_model=SubmitGateOut)
def submit_gate(
    workflow_id: str,
    run_id: str,
    body: SubmitGateIn,
    request: Request,
) -> SubmitGateOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404)
    if not is_safe_path_segment(body.video):
        raise HTTPException(status_code=400)
    if not is_safe_path_segment(body.token):
        raise HTTPException(status_code=400)

    matching_gate: dict[str, Any] | None = None
    response_path = run_dir / body.video / "gates" / f"{body.token}.json"
    for _ts, source, event in read_events(run_dir):
        if (
            _is_well_formed_gate_event(source, event)
            and source == body.video
            and event.get("token") == body.token
            and not response_path.exists()
        ):
            matching_gate = event
    if matching_gate is None:
        raise HTTPException(status_code=404)

    decision = body.decision
    choice = decision.get("choice")
    if not isinstance(choice, str):
        raise HTTPException(status_code=400)

    shape = matching_gate.get("shape")
    normalized_decision: dict[str, Any] = {"choice": choice}
    if shape == "approval":
        if choice not in {"approve", "reject"}:
            raise HTTPException(status_code=400)
        if isinstance(decision.get("note"), str):
            normalized_decision["note"] = decision["note"]
    elif shape == "choice":
        options = matching_gate.get("options")
        if not isinstance(options, list) or choice not in options:
            raise HTTPException(status_code=400)
        if isinstance(decision.get("note"), str):
            normalized_decision["note"] = decision["note"]
    elif shape == "selection":
        if choice not in {"approve", "reject"}:
            raise HTTPException(status_code=400)
        if "note" in decision and not isinstance(decision["note"], str):
            raise HTTPException(status_code=400)
        if choice == "approve":
            keep = decision.get("keep", [])
            redo = decision.get("redo", [])
            if not isinstance(keep, list) or not all(isinstance(item, str) for item in keep):
                raise HTTPException(status_code=400)
            if not isinstance(redo, list) or not all(isinstance(item, str) for item in redo):
                raise HTTPException(status_code=400)
            items = matching_gate.get("items")
            if not isinstance(items, list) or not all(
                isinstance(item, dict) and isinstance(item.get("id"), str) for item in items
            ):
                raise HTTPException(status_code=400)
            declared_ids = {item["id"] for item in items}
            if not set(keep) <= declared_ids or not set(redo) <= declared_ids:
                raise HTTPException(status_code=400)
            if not set(keep).isdisjoint(redo):
                raise HTTPException(status_code=400)
            normalized_decision = {
                "choice": "approve",
                "keep": keep,
                "redo": redo,
                "note": decision.get("note", ""),
            }
        else:
            if decision.get("keep") or decision.get("redo"):
                raise HTTPException(status_code=400)
            normalized_decision = {"choice": "reject"}
            if isinstance(decision.get("note"), str):
                normalized_decision["note"] = decision["note"]
    else:
        raise HTTPException(status_code=400)

    live = run_dir / body.video / "gates" / f"{body.token}.json"
    gates_dir = run_dir / body.video / "gates"
    if not live.resolve().is_relative_to(gates_dir.resolve()):
        raise HTTPException(status_code=400)
    secret_values = frozenset(v for v in _secrets(request).values() if v)
    redacted_decision = _redact_secrets(normalized_decision, secret_values)
    write_json_atomic(live, redacted_decision)
    return SubmitGateOut(ok=True)


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


@router.get("/workflows/{workflow_id}/runs/{run_id}/files", response_model=RunFilesOut)
def list_run_files(workflow_id: str, run_id: str, request: Request) -> RunFilesOut:
    _require_workflow(request, workflow_id)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404)
    run_root = run_dir.resolve()
    files: list[RunFileOut] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(run_root):
            continue
        relative = path.relative_to(run_dir)
        if (
            relative.name == "context.json"
            or resolved.name == "context.json"
            or relative.as_posix() == "shared/result.json"
            or resolved.relative_to(run_root).as_posix() == "shared/result.json"
            or any(part.startswith(".") for part in relative.parts)
        ):
            continue
        files.append(RunFileOut(path=relative.as_posix(), size=path.stat().st_size))
    files.sort(key=lambda item: item.path)
    return RunFilesOut(files=files)


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
    relative = resolved.relative_to(run_dir.resolve())
    if (
        resolved.name == "context.json"
        or relative.as_posix() == "shared/result.json"
        or any(part.startswith(".") for part in relative.parts)
    ):
        raise HTTPException(status_code=404)
    media_type, _encoding = mimetypes.guess_type(resolved.name)
    return FileResponse(resolved, media_type=media_type or "application/octet-stream")
