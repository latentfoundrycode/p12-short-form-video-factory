"""T2b-2c contract: a budget denial ends the run `stopped-budget`, and spend is surfaced.

Two supervisor-side behaviours complete the budget breaker's reporting surface (Architecture §5.4,
§4 records):

1. **Denial → `stopped-budget`.** When a video (or the prepare phase) aborts because the budget
   guard refused a paid call, the runner exits with `EXIT_BUDGET_DENIED`; the supervisor records the
   run as `stopped-budget` (a clean, actionable stop the UI can offer a top-up for) rather than a
   generic `failed`. The denied video itself is `stopped` (a video-level status; `stopped-budget` is
   request-level only). A user-requested stop still wins over a budget stop.

2. **Spend surfacing.** When a budget is configured, the finished request's `budget` block carries
   the per-meter spend this run booked in the ledger plus the ceilings it ran under, so a reader can
   see "spent X of Y" without parsing the ledger.

`_aggregate_status` is exercised directly for the precedence rules; the full runner→supervisor path
is exercised with stub workflows. No network, no real spend; ledgers/ceilings live under tmp_path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sfvf.context import BudgetConfig

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_events, read_request, read_video
from app.core.supervisor import RunBusy, _aggregate_status, run_request

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _run(workflow: Path, tmp_path: Path, **kwargs: object) -> object:
    return run_request(
        workflow,
        params={"topic": "test"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        **kwargs,
    )


# --- _aggregate_status precedence ---


def test_aggregate_budget_denied_is_stopped_budget() -> None:
    assert (
        _aggregate_status(["stopped"], atomic=False, stopped=False, budget_denied=True)
        == "stopped-budget"
    )


def test_aggregate_budget_denied_overrides_partial() -> None:
    # A run that spent to the ceiling mid-way is stopped-budget, not partial — even though one video
    # completed. Everything already computed is kept (the completed video stays complete).
    assert (
        _aggregate_status(["complete", "stopped"], atomic=False, stopped=False, budget_denied=True)
        == "stopped-budget"
    )


def test_aggregate_user_stop_wins_over_budget() -> None:
    # An explicit user stop is the user's intent and takes precedence over a concurrent budget stop.
    assert (
        _aggregate_status(["stopped"], atomic=False, stopped=True, budget_denied=True) == "stopped"
    )


def test_aggregate_without_budget_denial_is_unchanged() -> None:
    assert (
        _aggregate_status(["complete"], atomic=False, stopped=False, budget_denied=False)
        == "complete"
    )


# --- denial → stopped-budget (full path) ---


def test_budget_denied_video_ends_run_stopped_budget(tmp_path: Path) -> None:
    result = _run(STUBS / "budget_denied", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "budget-denied").iterdir())
    request = read_request(run_dir)
    assert request.status == "stopped-budget"
    # The denied video is stopped (clean stop), not failed.
    assert request.videos[0].status == "stopped"
    assert read_video(run_dir / "01").status == "stopped"
    # The distinguishing budget reason reached events.jsonl.
    assert any(
        event.get("t") == "log"
        and event.get("level") == "error"
        and event.get("reason") == "budget"
        for _, _, event in read_events(run_dir)
    )


# --- spend surfacing ---


def test_configured_run_surfaces_spend_in_request_budget(tmp_path: Path) -> None:
    budget = BudgetConfig(
        ledger_path=tmp_path / "budget" / "ledger.jsonl",
        kill_switch_path=None,
        per_run={"openrouter": 0.50},
        per_day={"openrouter": 2.00},
        estimates={"openrouter": 0.05},
    )
    result = _run(STUBS / "budget_spender", tmp_path, budget=budget)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "budget-spender").iterdir())
    request = read_request(run_dir)
    assert request.status == "complete"
    assert request.budget is not None
    # Reconciled actual (0.02), not the 0.05 reservation, surfaced per meter.
    assert request.budget["spend"] == pytest.approx({"openrouter": 0.02})
    # The ceilings this run ran under travel with the spend.
    assert request.budget["per_run"]["openrouter"] == pytest.approx(0.50)
    assert request.budget["per_day"]["openrouter"] == pytest.approx(2.00)


def test_run_without_budget_config_has_no_budget_block(tmp_path: Path) -> None:
    result = _run(STUBS / "succeeds", tmp_path)
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "succeeds").iterdir())
    assert read_request(run_dir).budget is None
