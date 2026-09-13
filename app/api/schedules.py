"""Schedules CRUD API — list/create/read/update/delete schedules.json (Architecture §5.7)."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.schedules import SCHEDULES_PATH, ScheduleEntry, read_schedules, write_schedules
from app.paths import is_safe_path_segment

router = APIRouter(prefix="/api")

_LOCK = threading.Lock()
_TIME_OF_DAY = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class ScheduleWriteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    days: list[int]
    time_of_day: str
    video_count: int = Field(ge=1)
    concurrency: int = Field(default=1, ge=1)
    params: dict[str, Any] = Field(default_factory=dict)
    gates_auto: bool
    allow_real_spend: bool = False

    # These validators mirror ScheduleEntry deliberately.
    @field_validator("workflow_id")
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


class ScheduleEntryOut(BaseModel):
    id: str
    workflow_id: str
    days: list[int]
    time_of_day: str
    video_count: int
    concurrency: int
    params: dict[str, Any]
    gates_auto: bool
    allow_real_spend: bool


class SchedulesOut(BaseModel):
    schedules: list[ScheduleEntryOut]


def _schedules_path(request: Request) -> Path:
    return cast(Path, getattr(request.app.state, "schedules_path", SCHEDULES_PATH))


def _entry_out(entry: ScheduleEntry) -> ScheduleEntryOut:
    return ScheduleEntryOut.model_validate(entry.model_dump(mode="json"))


def _require_safe_id(schedule_id: str) -> None:
    if not is_safe_path_segment(schedule_id):
        raise HTTPException(status_code=404)


def _index_of(entries: list[ScheduleEntry], schedule_id: str) -> int:
    for index, entry in enumerate(entries):
        if entry.id == schedule_id:
            return index
    raise HTTPException(status_code=404)


@router.get("/schedules", response_model=SchedulesOut)
def list_schedules(request: Request) -> SchedulesOut:
    entries = read_schedules(_schedules_path(request))
    return SchedulesOut(schedules=[_entry_out(entry) for entry in entries])


@router.post(
    "/schedules",
    status_code=status.HTTP_201_CREATED,
    response_model=ScheduleEntryOut,
)
def create_schedule(body: ScheduleWriteIn, request: Request) -> ScheduleEntryOut:
    path = _schedules_path(request)
    entry = ScheduleEntry(id=uuid.uuid4().hex, **body.model_dump())
    with _LOCK:
        entries = read_schedules(path)
        entries.append(entry)
        write_schedules(path, entries)
    return _entry_out(entry)


@router.get("/schedules/{schedule_id}", response_model=ScheduleEntryOut)
def get_schedule(schedule_id: str, request: Request) -> ScheduleEntryOut:
    _require_safe_id(schedule_id)
    for entry in read_schedules(_schedules_path(request)):
        if entry.id == schedule_id:
            return _entry_out(entry)
    raise HTTPException(status_code=404)


@router.put("/schedules/{schedule_id}", response_model=ScheduleEntryOut)
def update_schedule(
    schedule_id: str,
    body: ScheduleWriteIn,
    request: Request,
) -> ScheduleEntryOut:
    _require_safe_id(schedule_id)
    path = _schedules_path(request)
    with _LOCK:
        entries = read_schedules(path)
        index = _index_of(entries, schedule_id)
        updated = ScheduleEntry(id=schedule_id, **body.model_dump())
        entries[index] = updated
        write_schedules(path, entries)
    return _entry_out(updated)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(schedule_id: str, request: Request) -> None:
    _require_safe_id(schedule_id)
    path = _schedules_path(request)
    with _LOCK:
        entries = read_schedules(path)
        kept = [entry for entry in entries if entry.id != schedule_id]
        if len(kept) == len(entries):
            raise HTTPException(status_code=404)
        write_schedules(path, kept)
