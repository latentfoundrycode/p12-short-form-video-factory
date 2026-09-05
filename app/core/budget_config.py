"""Load the budget-breaker configuration into a `sfvf.context.BudgetConfig` (T2b-2a).

Activation layer for the T2b-1 SDK gate: the supervisor reads this and injects it into each run's
context.json so the child enforces ceilings/kill-switch before a paid call. Env-gated like secrets
— no `SFVF_BUDGET_CONFIG` means no budget (the gate stays inert). A configured-but-unreadable
file fails closed (raises `BudgetConfigError`) rather than running ungated.

SKELETON — signatures frozen by tests/api/test_budget_activation.py; the builder fills the bodies.
"""

from __future__ import annotations

import math
import os
import tomllib
from pathlib import Path

from sfvf.context import BudgetConfig

from app.paths import APP_ROOT


class BudgetConfigError(Exception):
    """The configured budget file is missing or malformed (fail closed)."""


def _as_amount(value: object) -> float:
    """Coerce a TOML ceiling/estimate to float. Bools and non-numbers fail closed."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BudgetConfigError("budget amount must be a finite number")
    amount = float(value)
    if not math.isfinite(amount):
        raise BudgetConfigError("budget amount must be a finite number")
    return amount


def load_budget_config() -> BudgetConfig | None:
    """Return the configured BudgetConfig, or None when no budget is configured.

    `SFVF_BUDGET_CONFIG` unset → None. Set → parse that TOML into per-meter per_run/per_day ceilings
    and per-meter reserve estimates, deriving the ledger and kill-switch paths from the state dir
    (`SFVF_BUDGET_STATE` or a default). A missing or malformed file raises `BudgetConfigError`.
    """
    config_path = os.environ.get("SFVF_BUDGET_CONFIG")
    if not config_path:
        return None
    try:
        with Path(config_path).open("rb") as handle:
            data = tomllib.load(handle)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError) as exc:
        raise BudgetConfigError(str(exc)) from exc

    per_run: dict[str, float] = {}
    per_day: dict[str, float] = {}
    estimates: dict[str, float] = {}
    for meter, table in data.items():
        if not isinstance(table, dict):
            continue
        if "per_run" in table:
            per_run[meter] = _as_amount(table["per_run"])
        if "per_day" in table:
            per_day[meter] = _as_amount(table["per_day"])
        if "estimate" in table:
            estimates[meter] = _as_amount(table["estimate"])

    state = Path(os.environ.get("SFVF_BUDGET_STATE") or (APP_ROOT / "state" / "budget"))
    return BudgetConfig(
        ledger_path=(state / "ledger.jsonl").resolve(),
        kill_switch_path=(state / "STOP").resolve(),
        per_run=per_run,
        per_day=per_day,
        estimates=estimates,
    )
