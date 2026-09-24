"""Stage-C contract: prepare-phase spend is persisted and counted (PRD §8.6, Architecture §4.1).

The shared prepare phase can spend real money once per run — e.g. web-sourcing a shared asset behind
a paid VLM relevance check — before any video runs. Today `_run_prepare` discards the cost the
engine aggregates from that phase, so the money lands in `events.jsonl` but in no durable record,
and both the Statistics tab (`aggregate_statistics`) and cost estimation walk only per-video
`video.json`. It is money-SAFE (the prepare phase is budget-gated like a paid call) but INVISIBLE.

This increment persists the prepare phase's aggregated cost into `request.json` as an optional
`prepare_cost` block, shaped exactly like a video's `cost` (`{uncached, actual}`), and counts its
`actual` in the Statistics tab. (Feeding it into per-run cost ESTIMATION is a separate follow-on:
the per-video Estimate needs a per-run-overhead decision.) Fixtures are raw records / a stub under
tmp_path — no network, no spend.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.env import EnvBlocked, EnvReady
from app.core.records import create_request, read_request, update_request, write_json_atomic
from app.core.statistics import aggregate_statistics
from app.core.supervisor import RunBusy, run_request

_STUBS = Path(__file__).resolve().parent.parent / "stubs"
_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)  # 6-month window: 2026-04 .. 2026-09


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


# --- records: request.json carries an optional prepare_cost block --------------------------------


def test_prepare_cost_defaults_to_none_and_is_omitted_when_absent(tmp_path: Path) -> None:
    create_request(
        tmp_path,
        run_id="r1",
        workflow={"id": "wf", "version": "1", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "running"}],
    )
    assert read_request(tmp_path).prepare_cost is None
    raw = json.loads((tmp_path / "request.json").read_text(encoding="utf-8"))
    assert "prepare_cost" not in raw  # optional field is not serialised when unset


def test_prepare_cost_round_trips_through_update_request(tmp_path: Path) -> None:
    create_request(
        tmp_path,
        run_id="r1",
        workflow={"id": "wf", "version": "1", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "running"}],
    )
    block = {"uncached": {"openrouter": 0.05}, "actual": {"openrouter": 0.05}}
    update_request(tmp_path, prepare_cost=block)
    assert read_request(tmp_path).prepare_cost == block


# --- supervisor: the prepare phase's aggregated cost is persisted into request.prepare_cost -------


def test_run_prepare_persists_the_prepare_phase_cost(tmp_path: Path) -> None:
    result = run_request(
        _STUBS / "prepare_emits_cost",
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next(next((tmp_path / "runs").iterdir()).iterdir())
    prepare_cost = read_request(run_dir).prepare_cost
    assert prepare_cost is not None
    # The stub's prepare emits one non-cached openrouter cost of 0.05.
    assert prepare_cost["actual"]["openrouter"] == pytest.approx(0.05)
    assert prepare_cost["uncached"]["openrouter"] == pytest.approx(0.05)


# --- statistics: prepare_cost actual is counted like video actual --------------------------------


def _write_run(
    runs_dir: Path,
    run_id: str,
    started_month: str,
    *,
    video_actual: dict[int, dict[str, float]],
    prepare_actual: dict[str, float] | None = None,
    status: str = "complete",
    dry_run: bool = False,
) -> None:
    started = f"{started_month}-05T00:00:00Z"
    run_dir = runs_dir / "wf" / run_id
    videos = sorted(video_actual)
    request: dict[str, object] = {
        "run_id": run_id,
        "workflow": {"id": "wf", "version": "1", "sdk": "1"},
        "started_utc": started,
        "ended_utc": f"{started_month}-05T00:01:00Z",
        "status": status,
        "params": {},
        "params_locked_utc": started,
        "dry_run": dry_run,
        "videos": [{"index": i, "status": "complete"} for i in videos],
    }
    if prepare_actual is not None:
        request["prepare_cost"] = {"uncached": prepare_actual, "actual": prepare_actual}
    write_json_atomic(run_dir / "request.json", request)
    for i in videos:
        write_json_atomic(
            run_dir / f"{i:02d}" / "video.json",
            {
                "index": i,
                "status": "complete",
                "started_utc": started,
                "ended_utc": f"{started_month}-05T00:01:00Z",
                "cost": {"actual": video_actual[i]},
            },
        )


def _fiat_total(runs: Path) -> float:
    series = {s.id: s for s in aggregate_statistics(runs, months=6, now=_NOW)}
    return series["fiat"].total


def test_prepare_cost_actual_is_added_to_the_spend_series(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # A run whose prepare spent 0.05 and whose one video spent 0.10 → the series must show 0.15,
    # not 0.10 (the prepare spend is real money and must appear in the Statistics tab).
    _write_run(
        runs,
        "r1",
        "2026-07",
        video_actual={1: {"openrouter": 0.10}},
        prepare_actual={"openrouter": 0.05},
    )
    assert _fiat_total(runs) == pytest.approx(0.15)


def test_prepare_cost_of_a_dry_run_is_excluded(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(
        runs,
        "r1",
        "2026-07",
        video_actual={1: {"openrouter": 0.10}},
        prepare_actual={"openrouter": 9.0},
        dry_run=True,
    )
    assert aggregate_statistics(runs, months=6, now=_NOW) == []  # dry runs spend nothing


def test_malformed_prepare_amount_is_skipped_not_fatal(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # A negative/non-finite prepare amount is dropped (tolerant reading, §8) while the good video
    # spend still counts.
    _write_run(
        runs,
        "r1",
        "2026-07",
        video_actual={1: {"openrouter": 0.10}},
        prepare_actual={"openrouter": -3.0},
    )
    assert _fiat_total(runs) == pytest.approx(0.10)
