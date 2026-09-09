"""C-4 contract: the atomic-workflow pre-flight budget check (§5.4b, attended core).

`check_atomic_budget(estimate, safety_factor, budget, run_id)` returns None when the estimated run
fits, else a refusal message naming the meter that does not. The required amount per meter is
`amount * safety_factor`, checked against BOTH ceilings' headroom: per_run minus this run's
reservations, and per_day minus today's total (from the ledger). A meter absent from a ceiling
map is unlimited. No estimate (empty per_meter) fits trivially. Read-only; fake ledgers under tmp.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from sfvf._budget import BudgetGuard, Ceilings
from sfvf.context import BudgetConfig

from app.core.env import EnvBlocked, EnvReady
from app.core.estimate import Estimate
from app.core.preflight import check_atomic_budget
from app.core.records import read_request, write_json_atomic
from app.core.supervisor import RunBusy, run_request

_STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _budget(tmp: Path, *, per_run: dict[str, float], per_day: dict[str, float]) -> BudgetConfig:
    return BudgetConfig(
        ledger_path=tmp / "budget" / "ledger.jsonl",
        kill_switch_path=None,
        per_run=per_run,
        per_day=per_day,
        estimates={},
    )


def _seed_day_spend(budget: BudgetConfig, meter: str, amount: float) -> None:
    """Book `amount` against today for `meter` under another run, to shrink per_day headroom."""
    guard = BudgetGuard(
        budget.ledger_path,
        ceilings=Ceilings(per_run={}, per_day={}),
        kill_switch_path=None,
        now=lambda: datetime.now(UTC),
    )
    guard.reserve(run_id="other-run", meter=meter, unit="usd", estimate=amount)


def _est(per_meter: dict[str, float]) -> Estimate:
    return Estimate(per_meter=per_meter, confidence="matched", matches=1)


def test_fits_within_ceilings_returns_none(tmp_path: Path) -> None:
    budget = _budget(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 2.0})
    assert check_atomic_budget(_est({"openrouter": 0.10}), 1.0, budget, "run-1") is None


def test_exceeding_per_run_after_safety_factor_refuses(tmp_path: Path) -> None:
    budget = _budget(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 100.0})
    # 0.8 * 1.5 = 1.2 > per_run 1.0 → refuse, naming the meter.
    msg = check_atomic_budget(_est({"openrouter": 0.8}), 1.5, budget, "run-1")
    assert msg is not None and "openrouter" in msg


def test_safety_factor_one_fits_where_higher_would_not(tmp_path: Path) -> None:
    budget = _budget(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 100.0})
    assert check_atomic_budget(_est({"openrouter": 0.8}), 1.0, budget, "run-1") is None


def test_exceeding_per_day_headroom_refuses(tmp_path: Path) -> None:
    budget = _budget(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 1.0})
    _seed_day_spend(budget, "openrouter", 0.7)  # leaves 0.3 of the per_day headroom
    msg = check_atomic_budget(_est({"openrouter": 0.5}), 1.0, budget, "run-1")
    assert msg is not None and "openrouter" in msg


def test_no_estimate_fits(tmp_path: Path) -> None:
    budget = _budget(tmp_path, per_run={"openrouter": 0.01}, per_day={"openrouter": 0.01})
    assert check_atomic_budget(Estimate({}, "none", 0), 1.0, budget, "run-1") is None


def test_meter_absent_from_ceilings_is_unlimited(tmp_path: Path) -> None:
    # higgsfield has no ceiling → any amount fits regardless.
    budget = _budget(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 1.0})
    assert check_atomic_budget(_est({"higgsfield": 500.0}), 2.0, budget, "run-1") is None


# --- integration: an atomic run refuses to start when history says it cannot finish ---


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _seed_complete_run(
    runs_dir: Path, workflow_id: str, run_id: str, *, params: dict, uncached: dict[str, float]
) -> None:
    run_dir = runs_dir / workflow_id / run_id
    write_json_atomic(
        run_dir / "request.json",
        {
            "run_id": run_id,
            "workflow": {"id": workflow_id, "version": "1", "sdk": "1"},
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "status": "complete",
            "params": params,
            "params_locked_utc": "2026-01-01T00:00:00Z",
            "dry_run": False,
            "videos": [{"index": 1, "status": "complete"}],
        },
    )
    write_json_atomic(
        run_dir / "01" / "video.json",
        {
            "index": 1,
            "status": "complete",
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "cost": {"uncached": uncached},
        },
    )


def test_atomic_run_refuses_to_start_when_estimate_exceeds_budget(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    # History: a comparable (model=A) complete run cost 5.0 openrouter uncached.
    _seed_complete_run(
        runs,
        "atomic-costly",
        "20260101-000000",
        params={"model": "A"},
        uncached={"openrouter": 5.0},
    )
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        kill_switch_path=None,
        per_run={"openrouter": 1.0},  # 5.0 * safety_factor(1.0) = 5.0 >> 1.0 → cannot finish
        per_day={"openrouter": 100.0},
        estimates={"openrouter": 0.05},
    )
    result = run_request(
        _STUBS / "atomic_costly",
        params={"model": "A"},
        video_count=1,
        concurrency=1,
        runs_dir=runs,
        ensure_env=_ready,
        budget=budget,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    # The launched run (not the seeded one) refused before running any video (main.py would raise).
    launched = [d for d in (runs / "atomic-costly").iterdir() if d.name != "20260101-000000"]
    assert len(launched) == 1
    request = read_request(launched[0])
    assert request.status == "stopped-budget"
    assert all(v.status == "stopped" for v in request.videos)
