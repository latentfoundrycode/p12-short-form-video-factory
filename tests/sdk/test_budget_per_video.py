"""TASK-SSN-B2 contract: a per-video CROSS-METER aggregate ceiling in BudgetGuard.

per_video_budget (a run setting from B1) caps the total reserved+actual spend for ONE video across
ALL meters -- the sum over (run_id, video_index) -- independent of the per-meter per_run/per_day
ceilings. `reserve()` refuses the call that would breach it. A released reserve (reconcile actual=0)
frees the aggregate again, so the reserve/release-on-failure taxonomy (Issue 6) is not regressed.
`video_index` is recorded on the reserved and actual ledger lines.

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/_budget.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf._budget import BudgetExceededError, BudgetGuard, Ceilings, read_run_spend


def _clock(moment: datetime):
    def now() -> datetime:
        return moment

    return now


def _ledger_lines(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _guard(
    tmp_path: Path,
    *,
    per_run: dict[str, float] | None = None,
    per_day: dict[str, float] | None = None,
    per_video: float | None = None,
) -> BudgetGuard:
    return BudgetGuard(
        tmp_path / "ledger.jsonl",
        ceilings=Ceilings(per_run=per_run or {}, per_day=per_day or {}),
        per_video_ceiling=per_video,
        now=_clock(datetime(2026, 9, 5, 12, 0, tzinfo=UTC)),
    )


def test_reserve_refuses_cross_meter_per_video_breach(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_video=8.0)
    guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=5.0, video_index=1)
    with pytest.raises(BudgetExceededError):
        # 5.0 (openrouter) + 4.0 (serpapi) = 9.0 across meters for video 1 > 8.0
        guard.reserve(run_id="r1", meter="serpapi", unit="usd", estimate=4.0, video_index=1)


def test_per_video_ceiling_is_scoped_per_video(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_video=8.0)
    guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=5.0, video_index=1)
    # A different video has its own per-video budget; 5.0 is fine on video 2.
    guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=5.0, video_index=2)


def test_released_reserve_frees_the_per_video_aggregate(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_video=8.0)
    token = guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=6.0, video_index=1)
    guard.reconcile(token, actual=0.0, note="released")
    # The 6.0 reserve was released, so a fresh 6.0 on the same video fits under 8.0.
    guard.reserve(run_id="r1", meter="serpapi", unit="usd", estimate=6.0, video_index=1)


def test_no_per_video_ceiling_allows_any_aggregate(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_video=None)
    guard.reserve(run_id="r1", meter="a", unit="usd", estimate=100.0, video_index=1)
    guard.reserve(run_id="r1", meter="b", unit="usd", estimate=100.0, video_index=1)


def test_video_index_recorded_on_reserved_and_actual_lines(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_video=8.0)
    token = guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=1.0, video_index=3)
    guard.reconcile(token, actual=1.0)
    lines = _ledger_lines(tmp_path / "ledger.jsonl")
    reserved = [line for line in lines if line.get("kind") == "reserved"]
    actual = [line for line in lines if line.get("kind") == "actual"]
    assert reserved and all(line["video_index"] == 3 for line in reserved)
    assert actual and all(line["video_index"] == 3 for line in actual)


def test_per_meter_ceilings_still_honoured_alongside_per_video(tmp_path: Path) -> None:
    # Regression: the per-meter per_run ceiling is enforced independently of the per-video sum.
    guard = _guard(tmp_path, per_run={"openrouter": 1.0}, per_video=100.0)
    guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=0.8, video_index=1)
    with pytest.raises(BudgetExceededError):
        guard.reserve(run_id="r1", meter="openrouter", unit="usd", estimate=0.5, video_index=1)


def test_malformed_video_index_does_not_break_read_run_spend(tmp_path: Path) -> None:
    # read_run_spend is best-effort: a corrupt / hand-edited ledger with a non-int video_index
    # (e.g. null) must not raise (a finished run's record write must never fail on a bad ledger).
    # The new video_index read must be defensively coerced, not int()-ed blindly (int(None) raises).
    ledger = tmp_path / "ledger.jsonl"
    line = {
        "kind": "reserved",
        "token": "t1",
        "run_id": "r1",
        "workflow_id": "",
        "meter": "openrouter",
        "unit": "usd",
        "amount": 1.0,
        "note": "",
        "video_index": None,
    }
    ledger.write_text(json.dumps(line) + "\n", encoding="utf-8")
    spend = read_run_spend(ledger, "r1")  # must not raise
    assert isinstance(spend, dict)
