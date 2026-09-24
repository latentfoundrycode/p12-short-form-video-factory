"""H26 contract: the durable forecast block is strictly event-ordered (C-2, Architecture §4.1).

A `forecast` event is recorded two ways: it is appended to `events.jsonl` and it updates
`request.json`'s `forecast` block to `{meter: {unit, amount, at_utc}}` as a soft reservation. H26:
those two writes must happen under a *single* lock hold, folded into `_RunState.record_event`, so
that the durable `request.forecast[meter]` always reflects the LAST forecast event appended for
that meter. The pre-H26 code took the run lock separately for the append and for the accumulator
write, so two videos in one request forecasting the same meter concurrently could leave
`request.forecast[meter]` holding an earlier event's value while `events.jsonl` shows a later one —
the durable reservation disagreeing with the event log.

These tests drive `record_event` directly (the shared mutation point the per-video consumer threads
contend on) with no network and no spend; fixtures live only under tmp_path.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.core.records import create_request, read_events, read_request
from app.core.supervisor import _RunState

_WF = {"id": "demo", "version": "1", "sdk": "1"}


def _new_run(run_dir: Path) -> None:
    """A minimal running request.json — the forecast fold reads/writes it via update_request."""
    create_request(
        run_dir,
        run_id="r1",
        workflow=_WF,
        params={},
        videos=[{"index": 1, "status": "running"}],
    )


def _forecast_event(meter: str, unit: str, amount: float) -> dict[str, object]:
    return {"t": "forecast", "meter": meter, "unit": unit, "amount": amount}


def _last_forecast_amount(run_dir: Path, meter: str) -> float:
    """The amount on the LAST forecast event for `meter` in events.jsonl (the event-order truth)."""
    latest: float | None = None
    for _ts, _source, event in read_events(run_dir):
        if event.get("t") == "forecast" and event.get("meter") == meter:
            latest = float(event["amount"])
    assert latest is not None, f"no forecast event for {meter} in events.jsonl"
    return latest


def test_record_event_folds_a_forecast_into_the_request_block(tmp_path: Path) -> None:
    # A single forecast through record_event lands in BOTH events.jsonl and request.forecast.
    _new_run(tmp_path)
    state = _RunState()
    state.record_event(tmp_path, _forecast_event("openrouter", "usd", 1.2), "runner")

    assert _last_forecast_amount(tmp_path, "openrouter") == pytest.approx(1.2)  # appended
    forecast = read_request(tmp_path).forecast
    assert forecast is not None
    entry = forecast["openrouter"]
    assert entry["unit"] == "usd"
    assert entry["amount"] == pytest.approx(1.2)
    assert isinstance(entry["at_utc"], str) and entry["at_utc"]  # stamped when recorded


def test_latest_per_meter_supersedes_and_distinct_meters_accumulate(tmp_path: Path) -> None:
    _new_run(tmp_path)
    state = _RunState()
    for amount in (500.0, 720.0):  # same meter — the later one wins
        state.record_event(tmp_path, _forecast_event("veo", "credits", amount), "runner")
    state.record_event(tmp_path, _forecast_event("openrouter", "usd", 1.2), "runner")

    forecast = read_request(tmp_path).forecast
    assert forecast is not None
    assert forecast["veo"]["amount"] == pytest.approx(720.0)  # superseded 500
    assert forecast["openrouter"]["amount"] == pytest.approx(1.2)  # distinct meter accumulates


def test_non_forecast_events_never_create_a_forecast_block(tmp_path: Path) -> None:
    _new_run(tmp_path)
    state = _RunState()
    state.record_event(tmp_path, {"t": "log", "level": "info", "msg": "hello"}, "runner")
    assert read_request(tmp_path).forecast is None


def test_malformed_forecast_is_logged_but_does_not_poison_the_block(tmp_path: Path) -> None:
    # A negative/non-finite amount fails _parse_forecast_event: the event is still appended, but it
    # must NOT be written into the durable reservation (tolerant reading, §8; matches C-2's guard).
    _new_run(tmp_path)
    state = _RunState()
    state.record_event(tmp_path, _forecast_event("veo", "credits", -3.0), "runner")
    assert read_request(tmp_path).forecast is None  # no valid forecast ever recorded


def test_concurrent_same_meter_forecasts_match_the_last_event(tmp_path: Path) -> None:
    # The H26 race: many per-video threads forecast the SAME meter through the shared _RunState.
    # Because the append and the accumulator write are one critical section, the thread that appends
    # last also writes the block last — so the durable request.forecast[meter] equals the LAST
    # forecast event in events.jsonl, deterministically, whatever the thread scheduling. The pre-H26
    # two-lock code could leave the block on an earlier event's value.
    _new_run(tmp_path)
    state = _RunState()
    amounts = [float(i) for i in range(1, 33)]
    barrier = threading.Barrier(len(amounts))

    def emit(amount: float) -> None:
        barrier.wait()  # release all threads together to maximize contention
        state.record_event(tmp_path, _forecast_event("veo", "credits", amount), "runner")

    threads = [threading.Thread(target=emit, args=(a,)) for a in amounts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    forecast = read_request(tmp_path).forecast
    assert forecast is not None
    # The durable reservation agrees with the event log's final word for the meter.
    assert forecast["veo"]["amount"] == pytest.approx(_last_forecast_amount(tmp_path, "veo"))
