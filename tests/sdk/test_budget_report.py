"""T2b-2c contract: post-run spend reporting read (`sfvf._budget.read_run_spend`).

After a run finishes, the supervisor surfaces what that run spent by reading the durable JSONL
ledger the gate wrote during the run (one `reserved` entry per priced call, superseded by an
`actual` on reconcile). `read_run_spend(ledger_path, run_id)` returns the per-meter effective total
for exactly that run: the reconciled actual when present, else the open reserved estimate (never
both), summed per meter, counting only entries stamped with the given run_id.

Unlike the gate's read (which fails closed so it can never let spend through on a corrupt ledger),
this reporting read is BEST-EFFORT: it runs at finalize on an already-finished run, so an unreadable
or corrupt ledger yields {} rather than turning a completed run into a recording failure. No
network, no real spend; fake ledgers live only under tmp_path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf._budget import BudgetGuard, Ceilings, read_run_spend


def _guard(
    ledger: Path,
    *,
    per_run: dict[str, float] | None = None,
    per_day: dict[str, float] | None = None,
) -> BudgetGuard:
    return BudgetGuard(
        ledger,
        ceilings=Ceilings(per_run=per_run or {}, per_day=per_day or {}),
        kill_switch_path=None,
        now=lambda: datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )


def test_missing_ledger_reports_nothing(tmp_path: Path) -> None:
    assert read_run_spend(tmp_path / "absent.jsonl", "run-1") == {}


def test_open_reservation_reports_the_estimate(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _guard(ledger, per_day={"openrouter": 10.0}).reserve(
        run_id="run-1", meter="openrouter", unit="EUR", estimate=0.05
    )
    assert read_run_spend(ledger, "run-1") == pytest.approx({"openrouter": 0.05})


def test_reconciled_actual_supersedes_the_reservation(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(ledger, per_day={"openrouter": 10.0})
    token = guard.reserve(run_id="run-1", meter="openrouter", unit="EUR", estimate=0.05)
    guard.reconcile(token, actual=0.017)
    # Only the actual counts — never the superseded reservation on top of it.
    assert read_run_spend(ledger, "run-1") == pytest.approx({"openrouter": 0.017})


def test_totals_are_summed_per_meter(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(ledger, per_day={"openrouter": 10.0, "higgsfield": 500.0})
    guard.reserve(run_id="run-1", meter="openrouter", unit="EUR", estimate=0.05)
    guard.reserve(run_id="run-1", meter="openrouter", unit="EUR", estimate=0.02)
    guard.reserve(run_id="run-1", meter="higgsfield", unit="credits", estimate=100.0)
    assert read_run_spend(ledger, "run-1") == pytest.approx(
        {"openrouter": 0.07, "higgsfield": 100.0}
    )


def test_only_the_named_run_is_counted(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    guard = _guard(ledger, per_day={"openrouter": 10.0})
    guard.reserve(run_id="run-1", meter="openrouter", unit="EUR", estimate=0.05)
    guard.reserve(run_id="run-2", meter="openrouter", unit="EUR", estimate=0.03)
    assert read_run_spend(ledger, "run-1") == pytest.approx({"openrouter": 0.05})
    assert read_run_spend(ledger, "run-2") == pytest.approx({"openrouter": 0.03})


def test_run_with_no_entries_reports_nothing(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    _guard(ledger, per_day={"openrouter": 10.0}).reserve(
        run_id="run-1", meter="openrouter", unit="EUR", estimate=0.05
    )
    assert read_run_spend(ledger, "no-such-run") == {}


def test_corrupt_ledger_reports_nothing_rather_than_raising(tmp_path: Path) -> None:
    # Reporting runs at finalize on an already-finished run: a corrupt ledger must NOT raise
    # (which would break the run's record write). It fails soft to {}, unlike the gate's read.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("{not valid json}\n", encoding="utf-8")
    assert read_run_spend(ledger, "run-1") == {}


def test_valid_json_line_with_unusable_amount_reports_nothing(tmp_path: Path) -> None:
    # A syntactically valid JSON entry whose amount is missing (or non-numeric/negative) passes the
    # JSON-shape check but breaks amount coercion downstream. Reporting must STILL fail soft to {} —
    # the ledger is a machine-wide file a child can append to, and this read must never raise into
    # the finished run's record write.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        '{"token":"t","kind":"reserved","meter":"openrouter","run_id":"run-1"}\n',
        encoding="utf-8",
    )
    assert read_run_spend(ledger, "run-1") == {}


def test_ledger_amount_too_large_for_float_reports_nothing(tmp_path: Path) -> None:
    # A valid-JSON entry whose amount is an integer too large to convert to float raises
    # OverflowError (an ArithmeticError, not a ValueError) during amount coercion. The best-effort
    # reader must still fail soft to {} — the contract is "never raise into the record write",
    # regardless of which exception the poisoned ledger provokes.
    ledger = tmp_path / "ledger.jsonl"
    huge = "1" + "0" * 400
    ledger.write_text(
        '{"token":"t","kind":"actual","meter":"openrouter","run_id":"run-1","amount":'
        + huge
        + "}\n",
        encoding="utf-8",
    )
    assert read_run_spend(ledger, "run-1") == {}
