import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.records import (
    VideoRecord,
    VideoRef,
    append_event,
    create_request,
    read_events,
    read_request,
    read_video,
    update_request,
    write_video,
)


def _pin_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen = datetime(2026, 8, 10, 14, 30, 22, tzinfo=UTC)
    monkeypatch.setattr("app.core.ids.utc_now", lambda: frozen)


def test_request_json_round_trip_omits_later_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    created = create_request(
        run_dir,
        run_id="20260810-143022",
        workflow={"id": "news-explainer", "version": "1.3.0", "sdk": "1"},
        params={"topic": "cafés", "duration_s": 45},
        videos=[{"index": 1, "status": "pending"}],
        atomic=False,
    )
    assert created.status == "running"
    assert created.ended_utc is None
    assert created.started_utc == "2026-08-10T14:30:22Z"
    assert created.params_locked_utc == "2026-08-10T14:30:22Z"

    raw = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
    assert raw["ended_utc"] is None
    assert "budget" not in raw
    assert "forecast" not in raw
    loaded = read_request(run_dir)
    assert loaded.params == {"topic": "cafés", "duration_s": 45}
    assert loaded.workflow.id == "news-explainer"


def test_update_request_does_not_mutate_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    create_request(
        run_dir,
        run_id="20260810-143022",
        workflow={"id": "news-explainer", "version": "1.0.0", "sdk": "1"},
        params={"topic": "locked"},
        videos=[{"index": 1, "status": "pending"}],
        atomic=False,
    )
    updated = update_request(
        run_dir,
        status="complete",
        ended_utc="2026-08-10T15:04:11Z",
        videos=[{"index": 1, "status": "complete"}],
        atomic=False,
    )
    assert updated.status == "complete"
    assert updated.ended_utc == "2026-08-10T15:04:11Z"
    assert updated.params == {"topic": "locked"}
    assert updated.params_locked_utc == "2026-08-10T14:30:22Z"
    assert read_request(run_dir).params == {"topic": "locked"}


def test_atomic_true_rejects_partial_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    create_request(
        run_dir,
        run_id="20260810-143022",
        workflow={"id": "news-explainer", "version": "1.0.0", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "pending"}],
        atomic=True,
    )
    with pytest.raises(ValueError, match="partial"):
        update_request(run_dir, status="partial", atomic=True)
    with pytest.raises(ValueError, match="partial"):
        create_request(
            tmp_path / "other",
            run_id="20260810-143022",
            workflow={"id": "news-explainer", "version": "1.0.0", "sdk": "1"},
            params={},
            videos=[{"index": 1, "status": "failed"}],
            status="partial",
            atomic=True,
        )


def test_video_json_round_trip_omits_later_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    written = write_video(
        video_dir,
        VideoRecord(
            index=1,
            status="running",
            started_utc="2026-08-10T14:30:22Z",
            ended_utc=None,
        ),
    )
    assert written.ended_utc is None
    raw = json.loads((video_dir / "video.json").read_text(encoding="utf-8"))
    assert set(raw) == {"index", "status", "started_utc", "ended_utc"}
    assert raw["ended_utc"] is None
    loaded = read_video(video_dir)
    assert loaded.index == 1
    assert loaded.status == "running"


def test_video_status_rejects_request_only_values() -> None:
    with pytest.raises(ValidationError):
        VideoRef.model_validate({"index": 1, "status": "partial"})
    with pytest.raises(ValidationError):
        VideoRef.model_validate({"index": 1, "status": "stopped-budget"})
    assert VideoRef.model_validate({"index": 1, "status": "pending"}).status == "pending"
    assert VideoRef.model_validate({"index": 1, "status": "stopped"}).status == "stopped"


def test_events_jsonl_round_trip_preserves_unicode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    payload = {"t": "log", "msg": "café 日本語"}
    append_event(run_dir, payload, source="01")
    append_event(run_dir, {"t": "stage", "index": 1}, source="prep")
    events = list(read_events(run_dir))
    assert events == [
        ("2026-08-10T14:30:22Z", "01", {"t": "log", "msg": "café 日本語"}),
        ("2026-08-10T14:30:22Z", "prep", {"t": "stage", "index": 1}),
    ]
    line = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()[0]
    envelope = json.loads(line)
    assert envelope["ts"] == "2026-08-10T14:30:22Z"
    assert envelope["source"] == "01"
    assert envelope["event"] == payload
    assert line.endswith("}")
    assert "\\u" not in line


def test_read_events_stops_at_torn_final_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_clock(monkeypatch)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    append_event(run_dir, {"t": "log", "msg": "one"}, source="01")
    append_event(run_dir, {"t": "log", "msg": "two"}, source="01")
    path = run_dir / "events.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write('{"ts":"t","source":"01","event":{"t":"log"')
    events = list(read_events(run_dir))
    assert events == [
        ("2026-08-10T14:30:22Z", "01", {"t": "log", "msg": "one"}),
        ("2026-08-10T14:30:22Z", "01", {"t": "log", "msg": "two"}),
    ]
