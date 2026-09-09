"""Atomic-workflow pre-flight budget check (Architecture §5.4b, attended core).

An atomic workflow's half-finished video is worthless, so its cost is committed up front rather than
incrementally. Before such a run starts, the estimated cost (times the declared `safety_factor`) is
checked against the remaining budget headroom for each meter; if it cannot fit, the run is refused
before any work is done, rather than stranding spend part-way. The mid-run forecast re-check, the
whole-run reservation, and scheduled-run skip/stop semantics are later increments (the last
needs the Stage-F scheduler).
"""

from __future__ import annotations

from sfvf._budget import BudgetGuard, Ceilings
from sfvf.context import BudgetConfig

from app.core.estimate import Estimate


def check_atomic_budget(
    estimate: Estimate,
    safety_factor: float,
    budget: BudgetConfig,
    run_id: str,
) -> str | None:
    """Return None if the estimated run fits every metered ceiling, else a refusal message.

    For each meter in `estimate.per_meter`, the required amount is `amount * safety_factor`. It must
    fit the remaining headroom of both ceilings that apply: `per_run[meter] - run_total(run_id)` and
    `per_day[meter] - day_total()`, read from the budget ledger. A meter absent from a ceiling
    map is unlimited. The first meter that does not fit yields a message naming it (so the caller
    refuses to start); if every meter fits (or there is no estimate) the result is None. Read-only.
    """
    guard = BudgetGuard(
        budget.ledger_path,
        ceilings=Ceilings(per_run=budget.per_run, per_day=budget.per_day),
        kill_switch_path=budget.kill_switch_path,
    )
    for meter, amount in estimate.per_meter.items():
        need = amount * safety_factor
        if meter in budget.per_run and need > budget.per_run[meter] - guard.run_total(
            run_id, meter
        ):
            return f"estimated {meter} cost {need:g} exceeds per-run budget"
        if meter in budget.per_day and need > budget.per_day[meter] - guard.day_total(meter):
            return f"estimated {meter} cost {need:g} exceeds per-day budget"
    return None
