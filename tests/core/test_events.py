import json

from app.core.events import to_event


def test_non_json_line_becomes_info_log() -> None:
    assert to_event("progress bar |||||") == {
        "t": "log",
        "level": "info",
        "msg": "progress bar |||||",
    }


def test_json_array_becomes_info_log() -> None:
    assert to_event("[1, 2]") == {"t": "log", "level": "info", "msg": "[1, 2]"}


def test_json_object_passes_through_including_unknown_t() -> None:
    raw = {"t": "novel", "x": 1}
    assert to_event(json.dumps(raw)) == raw


def test_heartbeat_passes_through() -> None:
    raw = {"t": "heartbeat", "name": "work", "waiting_on": "test"}
    assert to_event(json.dumps(raw)) == raw


def test_stage_totals_are_not_latched() -> None:
    first = {"t": "stage", "index": 1, "total": 2, "label": "start"}
    second = {"t": "stage", "index": 2, "total": 9, "label": "counted later"}
    assert to_event(json.dumps(first)) == first
    assert to_event(json.dumps(second)) == second
