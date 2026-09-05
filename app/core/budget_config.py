"""Load the budget-breaker configuration into a `sfvf.context.BudgetConfig` (T2b-2a).

Activation layer for the T2b-1 SDK gate: the supervisor reads this and injects it into each run's
context.json so the child enforces ceilings/kill-switch before a paid call. Env-gated like secrets
— no `SFVF_BUDGET_CONFIG` means no budget (the gate stays inert). A configured-but-unreadable
file fails closed (raises `BudgetConfigError`) rather than running ungated.

SKELETON — signatures frozen by tests/api/test_budget_activation.py; the builder fills the bodies.
"""

from __future__ import annotations

from sfvf.context import BudgetConfig


class BudgetConfigError(Exception):
    """The configured budget file is missing or malformed (fail closed)."""


def load_budget_config() -> BudgetConfig | None:
    """Return the configured BudgetConfig, or None when no budget is configured.

    `SFVF_BUDGET_CONFIG` unset → None. Set → parse that TOML into per-meter per_run/per_day ceilings
    and per-meter reserve estimates, deriving the ledger and kill-switch paths from the state dir
    (`SFVF_BUDGET_STATE` or a default). A missing or malformed file raises `BudgetConfigError`.
    """
    raise NotImplementedError
