"""Schedule-entry model and schedules.json persistence (Architecture §5.7).

Data layer only: a validated `ScheduleEntry` and atomic read/write of a JSON list. The scheduler
loop and CRUD API are later increments. Scheduled runs default to a free dry run; `allow_real_spend`
is off unless an entry opts in.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.records import _retry_on_permission_error
from app.paths import APP_ROOT, is_safe_path_segment

SCHEDULES_PATH = APP_ROOT / "schedules.json"

_TIME_OF_DAY = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleError(Exception):
    """schedules.json is missing-as-malformed, not a list, or contains an invalid entry."""


class ScheduleEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workflow_id: str
    days: list[int]
    time_of_day: str
    video_count: int = Field(ge=1)
    concurrency: int = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    gates_auto: bool
    allow_real_spend: bool = False

    @field_validator("id", "workflow_id")
    @classmethod
    def _safe_segment(cls, value: str) -> str:
        if not is_safe_path_segment(value):
            raise ValueError(f"not a safe path segment: {value!r}")
        return value

    @field_validator("days")
    @classmethod
    def _weekday_indices(cls, value: list[int]) -> list[int]:
        if not value or any(day < 0 or day > 6 for day in value):
            raise ValueError("days must be a non-empty list of weekday indices 0..6 (Monday=0)")
        return value

    @field_validator("time_of_day")
    @classmethod
    def _hhmm(cls, value: str) -> str:
        if _TIME_OF_DAY.fullmatch(value) is None:
            raise ValueError('time_of_day must be 24-hour zero-padded "HH:MM"')
        return value


def _write_json_list_atomic(path: Path, payload: list[dict[str, Any]]) -> None:
    """Atomic temp-file-then-rename write of a JSON array, mirroring `write_json_atomic`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _retry_on_permission_error(lambda: os.replace(tmp_path, path))  # noqa: PTH105  # os.replace is atomic on Windows
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def read_schedules(path: Path) -> list[ScheduleEntry]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScheduleError(f"malformed schedules JSON in {path}") from exc
    if not isinstance(payload, list):
        raise ScheduleError(f"expected a JSON list in {path}")
    try:
        return [ScheduleEntry.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise ScheduleError(f"invalid schedule entry in {path}") from exc


def write_schedules(path: Path, entries: list[ScheduleEntry]) -> None:
    _write_json_list_atomic(path, [entry.model_dump(mode="json") for entry in entries])
