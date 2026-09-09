"""C-3 contract: cost estimation from run history (PRD §7.3).

`estimate_cost` reads a workflow's prior runs and estimates per-meter cost for a prospective run:
- match on the `affects_cost` param values only (free-text params like topic are irrelevant);
- average the **`uncached`** per-meter cost (not `actual` — a resumed run that reused cached steps
  understates a fresh run);
- exclude failed / stopped / stopped-budget runs (partial pay) and dry runs (free);
- use at most the last 10 comparable runs (most recent by run id);
- state confidence: "matched" (param match), else "crude" (workflow-wide average), else "none".

Fixtures are written as raw run records under tmp_path — no network, no spend. A companion check
confirms the supervisor's `create_request` records `dry_run` so real dry runs are identifiable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.estimate import Estimate, estimate_cost
from app.core.records import create_request, read_request, write_json_atomic

_WF = "demo"


def _run(
    runs_dir: Path,
    run_id: str,
    *,
    params: dict[str, Any],
    uncached: dict[int, dict[str, float]],
    actual: dict[int, dict[str, float]] | None = None,
    status: str = "complete",
    dry_run: bool = False,
) -> None:
    """Write a raw run record: request.json + one video.json per entry in `uncached`."""
    run_dir = runs_dir / _WF / run_id
    videos = sorted(uncached)
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": run_id,
            "workflow": {"id": _WF, "version": "1", "sdk": "1"},
            "started_utc": "2026-09-09T00:00:00Z",
            "ended_utc": "2026-09-09T00:01:00Z",
            "status": status,
            "params": params,
            "params_locked_utc": "2026-09-09T00:00:00Z",
            "dry_run": dry_run,
            "videos": [{"index": i, "status": "complete"} for i in videos],
        },
    )
    for i in videos:
        cost: dict[str, Any] = {"uncached": uncached[i]}
        if actual is not None and i in actual:
            cost["actual"] = actual[i]
        write_json_atomic(
            run_dir / f"{i:02d}" / "video.json",
            {
                "index": i,
                "status": "complete",
                "started_utc": "2026-09-09T00:00:00Z",
                "ended_utc": "2026-09-09T00:01:00Z",
                "cost": cost,
            },
        )


def _keys(*names: str) -> frozenset[str]:
    return frozenset(names)


def test_no_history_is_confidence_none(tmp_path: Path) -> None:
    est = estimate_cost(tmp_path / "runs", _WF, {"model": "m", "topic": "x"}, _keys("model"))
    assert est == Estimate(per_meter={}, confidence="none", matches=0)


def test_matched_runs_average_uncached_per_meter(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # Two runs matching model=A (topic differs — irrelevant); openrouter uncached 0.04 and 0.06.
    _run(
        runs,
        "20260909-000001",
        params={"model": "A", "topic": "p"},
        uncached={1: {"openrouter": 0.04}},
    )
    _run(
        runs,
        "20260909-000002",
        params={"model": "A", "topic": "q"},
        uncached={1: {"openrouter": 0.06}},
    )
    est = estimate_cost(runs, _WF, {"model": "A", "topic": "z"}, _keys("model"))
    assert est.confidence == "matched"
    assert est.matches == 2
    assert est.per_meter["openrouter"] == pytest.approx(0.05)


def test_uncached_not_actual_feeds_estimate(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(
        runs,
        "20260909-000001",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.10}},
        actual={1: {"openrouter": 0.01}},  # cache-reused; must NOT be used
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.per_meter["openrouter"] == pytest.approx(0.10)


def test_non_matching_params_fall_back_to_crude(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "20260909-000001", params={"model": "A"}, uncached={1: {"openrouter": 0.20}})
    _run(runs, "20260909-000002", params={"model": "B"}, uncached={1: {"openrouter": 0.40}})
    # Asking for model=C matches neither → crude workflow-wide average of both.
    est = estimate_cost(runs, _WF, {"model": "C"}, _keys("model"))
    assert est.confidence == "crude"
    assert est.matches == 2
    assert est.per_meter["openrouter"] == pytest.approx(0.30)


def test_failed_stopped_and_dry_runs_are_excluded(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "20260909-000001", params={"model": "A"}, uncached={1: {"openrouter": 0.05}})
    _run(
        runs,
        "20260909-000002",
        params={"model": "A"},
        uncached={1: {"openrouter": 9.0}},
        status="failed",
    )
    _run(
        runs,
        "20260909-000003",
        params={"model": "A"},
        uncached={1: {"openrouter": 9.0}},
        status="stopped",
    )
    _run(
        runs,
        "20260909-000004",
        params={"model": "A"},
        uncached={1: {"openrouter": 9.0}},
        dry_run=True,
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.matches == 1  # only the one complete, non-dry run
    assert est.per_meter["openrouter"] == pytest.approx(0.05)


def test_only_last_ten_comparable_runs_are_used(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # 12 matched runs; the two OLDEST (by run id) must be dropped, keeping the 10 most recent.
    for n in range(1, 13):
        _run(
            runs,
            f"20260909-0000{n:02d}",
            params={"model": "A"},
            uncached={1: {"openrouter": float(n)}},
        )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.matches == 10
    # mean of 3..12 inclusive = 7.5 (1 and 2 dropped)
    assert est.per_meter["openrouter"] == pytest.approx(7.5)


def test_running_and_incomplete_runs_are_excluded(tmp_path: Path) -> None:
    # Only completed history feeds estimates: a still-`running` run (e.g. the current run at
    # admission) has no final cost and must not be counted.
    runs = tmp_path / "runs"
    _run(runs, "20260909-000001", params={"model": "A"}, uncached={1: {"openrouter": 0.05}})
    _run(
        runs,
        "20260909-000002",
        params={"model": "A"},
        uncached={1: {"openrouter": 9.0}},
        status="running",
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.matches == 1
    assert est.per_meter["openrouter"] == pytest.approx(0.05)


def test_partial_runs_are_included(tmp_path: Path) -> None:
    # `partial` is success-with-attrition, not a failure — its completed work is usable history.
    runs = tmp_path / "runs"
    _run(
        runs,
        "20260909-000001",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.05}},
        status="partial",
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.matches == 1
    assert est.per_meter["openrouter"] == pytest.approx(0.05)


def test_malformed_uncached_amounts_are_skipped(tmp_path: Path) -> None:
    # A hand-edited or corrupt record may carry an oversized-int / negative / non-finite uncached
    # amount. The estimator must skip those (not crash on float() overflow, not poison the average),
    # while still using the good meters — tolerant reading (§8), the C-1/C-2 lesson.
    runs = tmp_path / "runs"
    _run(runs, "20260909-000001", params={"model": "A"}, uncached={1: {"openrouter": 0.05}})
    _run(
        runs,
        "20260909-000002",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.05, "bad_over": 10**400, "bad_neg": -3.0}},
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.matches == 2
    assert est.per_meter["openrouter"] == pytest.approx(0.05)
    assert "bad_over" not in est.per_meter
    assert "bad_neg" not in est.per_meter


def test_create_request_records_dry_run(tmp_path: Path) -> None:
    # Production wiring: the run record must carry dry_run so the estimator can exclude dry runs.
    run_dir = tmp_path / "run"
    create_request(
        run_dir,
        run_id="r1",
        workflow={"id": _WF, "version": "1", "sdk": "1"},
        params={},
        videos=[{"index": 1, "status": "running"}],
        dry_run=True,
    )
    assert read_request(run_dir).dry_run is True
