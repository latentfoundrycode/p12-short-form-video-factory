"""F-1 contract: the schedule-entry model + schedules.json persistence (Architecture §5.7).

§5.7: "Reads `schedules.json`. When an entry is due it checks two conditions … if that workflow
already has an active run, the slot is skipped; if the budget is insufficient, the slot is skipped.
Otherwise the Generation Request starts with the saved settings … Each entry carries the flag
determining whether approval gates pause or pass automatically."

This increment is the DATA LAYER only: a validated `ScheduleEntry` (the saved settings for a slot)
and read/write of `schedules.json` (a list of entries). The scheduler engine that evaluates
due-ness and starts runs is F-2; the CRUD API is F-3. Per the owner decision (2026-09-12), scheduled
runs default to a free dry run — `allow_real_spend` is off by default and F-2 maps
`dry_run = not allow_real_spend`. No network, no runs started here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.schedules import ScheduleEntry, ScheduleError, read_schedules, write_schedules


def _entry(**overrides: object) -> ScheduleEntry:
    base: dict[str, object] = {
        "id": "sch-1",
        "workflow_id": "explainer",
        "days": [0, 2, 4],
        "time_of_day": "07:00",
        "video_count": 3,
        "params": {"topic": "physics"},
        "gates_auto": True,
    }
    base.update(overrides)
    return ScheduleEntry.model_validate(base)


def test_valid_entry_and_defaults() -> None:
    entry = _entry()
    assert entry.workflow_id == "explainer"
    assert entry.days == [0, 2, 4]
    assert entry.time_of_day == "07:00"
    assert entry.video_count == 3
    # Owner decision: scheduled runs are a free dry run unless real spend is explicitly enabled.
    assert entry.allow_real_spend is False
    # concurrency defaults to 1 (one run per workflow at a time; §2/§5.7).
    assert entry.concurrency == 1


def test_allow_real_spend_can_be_enabled() -> None:
    assert _entry(allow_real_spend=True).allow_real_spend is True


@pytest.mark.parametrize("bad_time", ["25:00", "7:00", "07:60", "0700", "abc", "24:00", ""])
def test_bad_time_of_day_is_rejected(bad_time: str) -> None:
    with pytest.raises(ValidationError):
        _entry(time_of_day=bad_time)


@pytest.mark.parametrize("bad_days", [[], [7], [-1], [0, 7]])
def test_bad_days_are_rejected(bad_days: list[int]) -> None:
    with pytest.raises(ValidationError):
        _entry(days=bad_days)


@pytest.mark.parametrize("bad_count", [0, -1])
def test_video_count_must_be_positive(bad_count: int) -> None:
    with pytest.raises(ValidationError):
        _entry(video_count=bad_count)


def test_concurrency_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        _entry(concurrency=0)


@pytest.mark.parametrize("field", ["workflow_id", "id"])
@pytest.mark.parametrize("unsafe", ["../escape", "a/b", "..", "."])
def test_unsafe_identifiers_are_rejected(field: str, unsafe: str) -> None:
    with pytest.raises(ValidationError):
        _entry(**{field: unsafe})


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        _entry(surprise="x")


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "schedules.json"
    entries = [
        _entry(),
        _entry(id="sch-2", workflow_id="collage", allow_real_spend=True, gates_auto=False),
    ]
    write_schedules(path, entries)
    loaded = read_schedules(path)
    assert loaded == entries


def test_read_missing_file_returns_empty(tmp_path: Path) -> None:
    assert read_schedules(tmp_path / "nope.json") == []


def test_read_malformed_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "schedules.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScheduleError):
        read_schedules(path)


def test_read_rejects_non_list_payload(tmp_path: Path) -> None:
    path = tmp_path / "schedules.json"
    path.write_text('{"entries": []}', encoding="utf-8")
    with pytest.raises(ScheduleError):
        read_schedules(path)
