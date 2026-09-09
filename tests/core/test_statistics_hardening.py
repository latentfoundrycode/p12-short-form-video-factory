"""C-5a review hardening: two gaps the decorrelated review surfaced on spend aggregation.

1. A `quota` meter (read from the provider, not summed as spend — §7.1) must never appear as a spend
   series even if a record carried one in cost["actual"].
2. Per-month sums are finiteness-guarded, but a series-wide total could still overflow to inf, which
   serialises to invalid JSON. The total must stay finite.

These lock review findings; they are not part of the frozen contract in test_statistics.py.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.core.records import write_json_atomic
from app.core.statistics import aggregate_statistics

_NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)


def _write_run(runs: Path, run_id: str, started_month: str, actual: dict[str, float]) -> None:
    started = f"{started_month}-05T00:00:00Z"
    run_dir = runs / "wf" / run_id
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": run_id,
            "workflow": {"id": "wf", "version": "1", "sdk": "1"},
            "started_utc": started,
            "ended_utc": started,
            "status": "complete",
            "params": {},
            "params_locked_utc": started,
            "dry_run": False,
            "videos": [{"index": 1, "status": "complete"}],
        },
    )
    write_json_atomic(
        run_dir / "01" / "video.json",
        {
            "index": 1,
            "status": "complete",
            "started_utc": started,
            "ended_utc": started,
            "cost": {"actual": actual},
        },
    )


def test_quota_meter_is_not_a_spend_series(tmp_path: Path) -> None:
    # elevenlabs is a quota meter in the default registry; even if it appears in actual cost it must
    # not become a spend series (the fiat spend alongside it still shows).
    runs = tmp_path / "runs"
    _write_run(runs, "r1", "2026-06", {"openrouter": 0.10, "elevenlabs": 1000.0})
    series = {s.id: s for s in aggregate_statistics(runs, months=6, now=_NOW)}
    assert "elevenlabs" not in series
    assert series["fiat"].total == pytest.approx(0.10)


def test_series_total_stays_finite_on_overflow(tmp_path: Path) -> None:
    # Two finite per-month buckets can sum past float max; the series total must not become inf
    # (which would serialise to invalid JSON), matching the per-meter finiteness guard.
    runs = tmp_path / "runs"
    _write_run(runs, "r-aug", "2026-08", {"openrouter": 1e308})
    _write_run(runs, "r-sep", "2026-09", {"openrouter": 1e308})
    fiat = next(s for s in aggregate_statistics(runs, months=6, now=_NOW) if s.id == "fiat")
    assert math.isfinite(fiat.total)
