"""H64 contract: prepare-phase cost enters cost estimation as a per-RUN overhead (Stage-C).

C-4/H27 made the estimate PER-VIDEO (scaled by the requested video count). But a run also pays a
one-off SHARED prepare cost (persisted to `request.prepare_cost` by the statistics increment), which
is NOT per-video: it is incurred once per run regardless of how many videos the run makes. So the
estimate must carry that overhead separately and `scale_estimate` must add it ONCE, not multiply it
by the count — otherwise a multi-video run's estimate double-counts (or, today, omits) the prepare
spend, and the C-3 atomic pre-flight admits over the true cost.

`Estimate` gains `prepare_per_meter` (the per-run prepare overhead, averaged over the comparable
runs' `prepare_cost["uncached"]`, same runs-with-the-meter averaging as the per-video figure).
`scale_estimate(est, count)` returns `per_meter[m] = est.per_meter[m]*count + prepare_per_meter[m]`
and folds the overhead in (empty `prepare_per_meter` on the result, so re-scaling never
double-adds). A run with no prepare cost estimates an empty overhead — backward-compatible.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.estimate import Estimate, estimate_cost, scale_estimate
from app.core.records import write_json_atomic

_WF = "demo"


def _run(
    runs_dir: Path,
    run_id: str,
    *,
    params: dict[str, Any],
    uncached: dict[int, dict[str, float]],
    prepare_uncached: dict[str, float] | None = None,
    status: str = "complete",
    dry_run: bool = False,
) -> None:
    """Write a raw run: request.json (+ a prepare_cost block when given) + one video.json each."""
    run_dir = runs_dir / _WF / run_id
    videos = sorted(uncached)
    request: dict[str, Any] = {
        "run_id": run_id,
        "workflow": {"id": _WF, "version": "1", "sdk": "1"},
        "started_utc": "2026-09-09T00:00:00Z",
        "ended_utc": "2026-09-09T00:01:00Z",
        "status": status,
        "params": params,
        "params_locked_utc": "2026-09-09T00:00:00Z",
        "dry_run": dry_run,
        "videos": [{"index": i, "status": "complete"} for i in videos],
    }
    if prepare_uncached is not None:
        request["prepare_cost"] = {"uncached": prepare_uncached, "actual": prepare_uncached}
    write_json_atomic(run_dir / "request.json", request)
    for i in videos:
        write_json_atomic(
            run_dir / f"{i:02d}" / "video.json",
            {
                "index": i,
                "status": "complete",
                "started_utc": "2026-09-09T00:00:00Z",
                "ended_utc": "2026-09-09T00:01:00Z",
                "cost": {"uncached": uncached[i]},
            },
        )


def _keys(*names: str) -> frozenset[str]:
    return frozenset(names)


def test_estimate_reads_prepare_overhead_per_run(tmp_path: Path) -> None:
    # Two matched runs, each with a per-run prepare cost of openrouter 0.05 and one video at 0.02.
    # The per-video figure is 0.02; the prepare overhead is 0.05 (per run, not per video).
    runs = tmp_path / "runs"
    _run(
        runs,
        "20260909-000001",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.02}},
        prepare_uncached={"openrouter": 0.05},
    )
    _run(
        runs,
        "20260909-000002",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.02}},
        prepare_uncached={"openrouter": 0.05},
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.per_meter["openrouter"] == pytest.approx(0.02)
    assert est.prepare_per_meter["openrouter"] == pytest.approx(0.05)


def test_scale_adds_prepare_overhead_once_not_per_video(tmp_path: Path) -> None:
    est = Estimate(
        per_meter={"openrouter": 0.02},
        confidence="matched",
        matches=2,
        prepare_per_meter={"openrouter": 0.05},
    )
    scaled = scale_estimate(est, 3)
    # per-video 0.02 x 3 videos = 0.06, plus the ONE-off prepare overhead 0.05 = 0.11.
    assert scaled.per_meter["openrouter"] == pytest.approx(0.11)
    assert scaled.confidence == "matched" and scaled.matches == 2
    # The overhead is folded into per_meter and cleared, so re-scaling cannot double-add it.
    assert scaled.prepare_per_meter == {}


def test_runs_without_prepare_cost_are_backward_compatible(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "20260909-000001", params={"model": "A"}, uncached={1: {"openrouter": 0.03}})
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.prepare_per_meter == {}
    scaled = scale_estimate(est, 4)
    assert scaled.per_meter["openrouter"] == pytest.approx(0.12)  # pure per-video x count


def test_prepare_overhead_averages_over_runs_that_incurred_the_meter(tmp_path: Path) -> None:
    # One run had a prepare openrouter cost, the other had no prepare block. Consistent with the
    # per-video figure's averaging, the overhead is the mean over runs that HAVE the meter (0.06),
    # not diluted by the run that never incurred it.
    runs = tmp_path / "runs"
    _run(
        runs,
        "20260909-000001",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.02}},
        prepare_uncached={"openrouter": 0.06},
    )
    _run(runs, "20260909-000002", params={"model": "A"}, uncached={1: {"openrouter": 0.02}})
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.prepare_per_meter["openrouter"] == pytest.approx(0.06)


def test_malformed_prepare_amount_is_skipped(tmp_path: Path) -> None:
    # A negative/oversized prepare amount is dropped (tolerant reading, §8); good meters survive.
    runs = tmp_path / "runs"
    _run(
        runs,
        "20260909-000001",
        params={"model": "A"},
        uncached={1: {"openrouter": 0.02}},
        prepare_uncached={"openrouter": 0.05, "bad_neg": -1.0, "bad_over": 10**400},
    )
    est = estimate_cost(runs, _WF, {"model": "A"}, _keys("model"))
    assert est.prepare_per_meter["openrouter"] == pytest.approx(0.05)
    assert "bad_neg" not in est.prepare_per_meter
    assert "bad_over" not in est.prepare_per_meter
