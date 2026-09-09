"""Contract: spend-over-time aggregation for the Statistics tab (PRD §8.6, §7.1).

Sum the **actual** per-meter spend of every non-dry run, bucketed by calendar month over a trailing
window. Fiat meters combine into one series (euros are euros); credit meters never combine with one
another; an unknown meter stands alone as its own credit line. Every real charge counts, so stopped
and failed runs are included (they spent money) and only dry runs are excluded. Malformed values are
skipped. Fixtures are raw run records under tmp_path — no network, no spend.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.core.meters import MeterInfo
from app.core.records import write_json_atomic
from app.core.statistics import aggregate_statistics

# A fixed reference: window of 6 months ending 2026-09 is 2026-04 .. 2026-09 inclusive.
_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def _write_run(
    runs_dir: Path,
    workflow: str,
    run_id: str,
    started_month: str,
    actual: dict[int, dict[str, float]],
    *,
    status: str = "complete",
    dry_run: bool = False,
) -> None:
    """Write a raw run: request.json (dated `started_month`-05) + one video.json per entry."""
    started = f"{started_month}-05T00:00:00Z"
    run_dir = runs_dir / workflow / run_id
    videos = sorted(actual)
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": run_id,
            "workflow": {"id": workflow, "version": "1", "sdk": "1"},
            "started_utc": started,
            "ended_utc": f"{started_month}-05T00:01:00Z",
            "status": status,
            "params": {},
            "params_locked_utc": started,
            "dry_run": dry_run,
            "videos": [{"index": i, "status": "complete"} for i in videos],
        },
    )
    for i in videos:
        write_json_atomic(
            run_dir / f"{i:02d}" / "video.json",
            {
                "index": i,
                "status": "complete",
                "started_utc": started,
                "ended_utc": f"{started_month}-05T00:01:00Z",
                "cost": {"actual": actual[i]},
            },
        )


def _series_by_id(runs: Path, **kwargs: Any) -> dict[str, Any]:
    result = aggregate_statistics(runs, months=6, now=_NOW, **kwargs)
    return {s.id: s for s in result}


def test_no_runs_gives_no_series(tmp_path: Path) -> None:
    assert aggregate_statistics(tmp_path / "runs", months=6, now=_NOW) == []


def test_single_fiat_meter_buckets_and_window(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, "wf", "r-may", "2026-05", {1: {"openrouter": 0.10}})
    _write_run(runs, "wf", "r-jul", "2026-07", {1: {"openrouter": 0.30}})
    _write_run(runs, "wf", "r-old", "2026-01", {1: {"openrouter": 9.0}})  # before window → excluded
    series = _series_by_id(runs)
    assert set(series) == {"fiat"}
    fiat = series["fiat"]
    assert fiat.kind == "fiat"
    assert fiat.unit == "usd"
    assert fiat.providers == ["OpenRouter"]
    assert [b.month for b in fiat.buckets] == [
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    amounts = {b.month: b.amount for b in fiat.buckets}
    assert amounts["2026-05"] == pytest.approx(0.10)
    assert amounts["2026-07"] == pytest.approx(0.30)
    assert amounts["2026-04"] == 0.0
    assert fiat.total == pytest.approx(0.40)


def test_multiple_fiat_providers_combine_into_one_series(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    reg = {
        "openrouter": MeterInfo("fiat", "OpenRouter", "usd"),
        "anthropic": MeterInfo("fiat", "Anthropic", "usd"),
    }
    _write_run(runs, "wf", "r1", "2026-05", {1: {"openrouter": 0.10, "anthropic": 0.20}})
    series = _series_by_id(runs, registry=reg)
    assert set(series) == {"fiat"}
    fiat = series["fiat"]
    assert fiat.providers == ["Anthropic", "OpenRouter"]  # sorted
    assert {b.month: b.amount for b in fiat.buckets}["2026-05"] == pytest.approx(0.30)
    assert fiat.total == pytest.approx(0.30)


def test_credit_providers_never_combine(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    reg = {
        "higgsfield": MeterInfo("credit", "Higgsfield", "credits"),
        "runway": MeterInfo("credit", "Runway", "credits"),
    }
    _write_run(runs, "wf", "r1", "2026-06", {1: {"higgsfield": 10.0, "runway": 5.0}})
    result = aggregate_statistics(runs, months=6, now=_NOW, registry=reg)
    ids = {s.id for s in result}
    assert ids == {"higgsfield", "runway"}
    hf = next(s for s in result if s.id == "higgsfield")
    assert hf.kind == "credit"
    assert hf.total == pytest.approx(10.0)
    assert next(s for s in result if s.id == "runway").total == pytest.approx(5.0)


def test_unknown_meter_is_a_standalone_credit_series(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    reg = {"openrouter": MeterInfo("fiat", "OpenRouter", "usd")}
    _write_run(runs, "wf", "r1", "2026-06", {1: {"openrouter": 0.10, "mystery": 3.0}})
    series = _series_by_id(runs, registry=reg)
    assert "mystery" in series
    assert series["mystery"].kind == "credit"  # never merged into fiat
    assert series["mystery"].total == pytest.approx(3.0)
    assert series["fiat"].total == pytest.approx(0.10)


def test_dry_runs_excluded_stopped_and_failed_included(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, "wf", "r-ok", "2026-06", {1: {"openrouter": 0.10}}, status="complete")
    _write_run(runs, "wf", "r-stop", "2026-06", {1: {"openrouter": 0.05}}, status="stopped")
    _write_run(runs, "wf", "r-fail", "2026-06", {1: {"openrouter": 0.02}}, status="failed")
    _write_run(runs, "wf", "r-dry", "2026-06", {1: {"openrouter": 9.0}}, dry_run=True)
    series = _series_by_id(runs)
    assert series["fiat"].total == pytest.approx(0.17)  # 0.10 + 0.05 + 0.02, dry 9.0 excluded


def test_malformed_amounts_are_skipped(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(
        runs,
        "wf",
        "r1",
        "2026-06",
        {1: {"openrouter": 0.10, "bad_over": 10**400, "bad_neg": -3.0}},
    )
    series = _series_by_id(runs)
    assert series["fiat"].total == pytest.approx(0.10)
    assert "bad_over" not in series
    assert "bad_neg" not in series


def test_actual_not_uncached_is_used(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_dir = runs / "wf" / "r1"
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": "r1",
            "workflow": {"id": "wf", "version": "1", "sdk": "1"},
            "started_utc": "2026-06-05T00:00:00Z",
            "ended_utc": "2026-06-05T00:01:00Z",
            "status": "complete",
            "params": {},
            "params_locked_utc": "2026-06-05T00:00:00Z",
            "dry_run": False,
            "videos": [{"index": 1, "status": "complete"}],
        },
    )
    write_json_atomic(
        run_dir / "01" / "video.json",
        {
            "index": 1,
            "status": "complete",
            "started_utc": "2026-06-05T00:00:00Z",
            "ended_utc": "2026-06-05T00:01:00Z",
            "cost": {"actual": {"openrouter": 0.10}, "uncached": {"openrouter": 0.99}},
        },
    )
    assert _series_by_id(runs)["fiat"].total == pytest.approx(0.10)


def test_fiat_series_is_first_then_credits_sorted_by_label(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    reg = {
        "openrouter": MeterInfo("fiat", "OpenRouter", "usd"),
        "higgsfield": MeterInfo("credit", "Higgsfield", "credits"),
        "runway": MeterInfo("credit", "Runway", "credits"),
    }
    _write_run(
        runs, "wf", "r1", "2026-06", {1: {"openrouter": 0.1, "higgsfield": 2.0, "runway": 1.0}}
    )
    result = aggregate_statistics(runs, months=6, now=_NOW, registry=reg)
    assert [s.id for s in result] == ["fiat", "higgsfield", "runway"]


def test_months_one_is_only_the_current_month(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, "wf", "r-sep", "2026-09", {1: {"openrouter": 0.10}})
    _write_run(runs, "wf", "r-aug", "2026-08", {1: {"openrouter": 0.20}})  # outside 1-month window
    result = aggregate_statistics(runs, months=1, now=_NOW)
    fiat = next(s for s in result if s.id == "fiat")
    assert [b.month for b in fiat.buckets] == ["2026-09"]
    assert fiat.total == pytest.approx(0.10)
