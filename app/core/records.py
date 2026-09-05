from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.core import ids as clock

_RETRY_ATTEMPTS = 10
_RETRY_DELAY_S = 0.02  # tests monkeypatch this to 0.0


def _retry_on_permission_error[T](op: Callable[[], T]) -> T:
    """Run op(); on a transient PermissionError (Windows atomic-replace/open race), retry a
    bounded number of times with a short delay, then re-raise the last error."""
    last: PermissionError | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return op()
        except PermissionError as exc:
            last = exc
            if attempt + 1 < _RETRY_ATTEMPTS:
                time.sleep(_RETRY_DELAY_S)
    if last is None:
        raise RuntimeError("retry helper exhausted without an error")
    raise last


type RequestStatus = Literal[
    "running", "complete", "partial", "stopped", "stopped-budget", "failed"
]
type VideoStatus = Literal["pending", "running", "complete", "failed", "stopped"]

REQUEST_OPTIONAL_FIELDS = ("budget", "forecast")
VIDEO_OPTIONAL_FIELDS = (
    "cost",
    "steps",
    "instructions",
    "library",
    "gates",
    "decisions",
    "artifacts",
    "self_review",
    "result",
    "quality",
    "error",
)


class _RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkflowRef(_RecordModel):
    id: str
    version: str
    sdk: str


class VideoRef(_RecordModel):
    index: int
    status: VideoStatus


class RequestRecord(_RecordModel):
    run_id: str
    workflow: WorkflowRef
    started_utc: str
    ended_utc: str | None
    status: RequestStatus
    params: dict[str, Any]
    params_locked_utc: str
    videos: list[VideoRef]
    budget: dict[str, Any] | None = None
    forecast: dict[str, Any] | None = None


class VideoRecord(_RecordModel):
    index: int
    status: VideoStatus
    started_utc: str
    ended_utc: str | None
    cost: dict[str, Any] | None = None
    steps: list[Any] | None = None
    instructions: dict[str, Any] | None = None
    library: list[Any] | None = None
    gates: list[Any] | None = None
    decisions: list[Any] | None = None
    artifacts: list[Any] | None = None
    self_review: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None
    error: Any | None = None


def _dump_owned(model: _RecordModel, optional: tuple[str, ...]) -> dict[str, Any]:
    data = model.model_dump(mode="json")
    for key in optional:
        if data.get(key) is None:
            data.pop(key, None)
    return data


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _retry_on_permission_error(lambda: os.replace(tmp_path, path))  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    text = _retry_on_permission_error(lambda: path.read_text(encoding="utf-8"))
    payload: Any = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError(f"expected a JSON object in {path}")
    return payload


def _reject_atomic_partial(status: RequestStatus, *, atomic: bool) -> None:
    if atomic and status == "partial":
        raise ValueError("atomic workflows cannot be recorded as partial")


def create_request(
    run_dir: Path,
    *,
    run_id: str,
    workflow: WorkflowRef | Mapping[str, str],
    params: dict[str, Any],
    videos: Sequence[VideoRef | Mapping[str, Any]],
    atomic: bool = False,
    status: RequestStatus = "running",
) -> RequestRecord:
    _reject_atomic_partial(status, atomic=atomic)
    stamp = clock.format_utc_z(clock.utc_now())
    record = RequestRecord(
        run_id=run_id,
        workflow=WorkflowRef.model_validate(workflow),
        started_utc=stamp,
        ended_utc=None,
        status=status,
        params=params,
        params_locked_utc=stamp,
        videos=[VideoRef.model_validate(video) for video in videos],
    )
    write_json_atomic(run_dir / "request.json", _dump_owned(record, REQUEST_OPTIONAL_FIELDS))
    return record


def read_request(run_dir: Path) -> RequestRecord:
    return RequestRecord.model_validate(read_json(run_dir / "request.json"))


def update_request(
    run_dir: Path,
    *,
    atomic: bool = False,
    status: RequestStatus | None = None,
    ended_utc: str | None = None,
    videos: Sequence[VideoRef | Mapping[str, Any]] | None = None,
) -> RequestRecord:
    current = read_request(run_dir)
    new_status = current.status if status is None else status
    _reject_atomic_partial(new_status, atomic=atomic)
    updated = current.model_copy(
        update={
            "status": new_status,
            "ended_utc": current.ended_utc if ended_utc is None else ended_utc,
            "videos": (
                current.videos
                if videos is None
                else [VideoRef.model_validate(video) for video in videos]
            ),
        }
    )
    write_json_atomic(run_dir / "request.json", _dump_owned(updated, REQUEST_OPTIONAL_FIELDS))
    return updated


def write_video(video_dir: Path, record: VideoRecord) -> VideoRecord:
    write_json_atomic(video_dir / "video.json", _dump_owned(record, VIDEO_OPTIONAL_FIELDS))
    return record


def read_video(video_dir: Path) -> VideoRecord:
    return VideoRecord.model_validate(read_json(video_dir / "video.json"))


def append_event(run_dir: Path, event: dict[str, Any], *, source: str) -> None:
    path = run_dir / "events.jsonl"
    envelope = {"ts": clock.format_utc_z(clock.utc_now()), "source": source, "event": event}
    line = json.dumps(envelope, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_events(run_dir: Path) -> Iterator[tuple[str, str, dict[str, Any]]]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(envelope, dict) or not {"ts", "source", "event"} <= envelope.keys():
            return
        yield envelope["ts"], envelope["source"], envelope["event"]
