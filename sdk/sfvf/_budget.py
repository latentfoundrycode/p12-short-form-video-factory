"""Budget circuit-breaker engine: the minimal money-safety backstop (Architecture §5.4).

Reserve-then-reconcile against a durable JSONL ledger, restricted to the safety subset needed before
any live paid call. Per-meter ceilings (per-run and per-day) plus an operator kill-switch. Full
per-provider metering, cost events, and forecasts are Stage C and will extend this file.

SKELETON — signatures are frozen by tests/sdk/test_budget.py; the builder implements the bodies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class BudgetError(RuntimeError):
    """Base class for budget-breaker refusals."""


class BudgetExceededError(BudgetError):
    """A reservation would breach a per-run or per-day ceiling."""


class KillSwitchEngagedError(BudgetError):
    """The operator kill-switch is engaged; no paid call may proceed."""


@dataclass(frozen=True)
class Ceilings:
    """Per-meter spend ceilings. A meter absent from a map is unlimited."""

    per_run: Mapping[str, float]
    per_day: Mapping[str, float]


def _default_now() -> datetime:
    return datetime.now(UTC)


class BudgetGuard:
    """Enforces ceilings against a JSONL ledger; reserve before a call, reconcile after."""

    def __init__(
        self,
        ledger_path: Path,
        *,
        ceilings: Ceilings,
        kill_switch_path: Path | None = None,
        now: Callable[[], datetime] = _default_now,
    ) -> None:
        raise NotImplementedError

    def reserve(
        self, *, run_id: str, meter: str, unit: str, estimate: float, note: str = ""
    ) -> str:
        raise NotImplementedError

    def reconcile(self, token: str, *, actual: float, note: str = "") -> None:
        raise NotImplementedError

    def day_total(self, meter: str) -> float:
        raise NotImplementedError

    def run_total(self, run_id: str, meter: str) -> float:
        raise NotImplementedError
