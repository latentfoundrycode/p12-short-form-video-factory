"""H19(b)/H20(c) contract: reconcile surfaces an after-the-fact ceiling breach (record-only).

`reserve` is the fail-closed gate BEFORE a paid call. But a single UNDER-estimated call whose real
reconciled `actual` exceeds the ceiling is allowed after the fact (the money is already spent). For
a multi-call run the next `reserve` then denies (the actual now counts), but for an ATOMIC
single-call run there is no subsequent reserve, so the overshoot is currently entirely silent.

H19(b)/H20(c): `reconcile` now RECORDS the breach — after durably appending the `actual` line, it
re-checks the reconciled per-run and per-day totals against the ceilings and RETURNS the breaches
(record-only: it never raises on a breach, because the spend already happened; it still raises on a
corrupt ledger or a bad amount). `Context.record_cost` emits a `budget_breach` event per breach so
an operator sees the overshoot in the run record. This does not halt the run — its value is
visibility, the fail-closed prevention stays with `reserve`. No network, no spend; ledger in tmp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf._budget import BudgetBreach, BudgetGuard, Ceilings
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths


def _guard(
    tmp: Path,
    *,
    per_run: dict[str, float] | None = None,
    per_day: dict[str, float] | None = None,
) -> BudgetGuard:
    return BudgetGuard(
        tmp / "ledger.jsonl",
        ceilings=Ceilings(per_run=per_run or {}, per_day=per_day or {}),
    )


# --- engine: reconcile reports breaches, record-only (never raises on a breach) ------------------


def test_reconcile_within_ceiling_reports_no_breach(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_run={"openrouter": 1.0})
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.1)
    assert guard.reconcile(token, actual=0.5) == []
    assert guard.run_total("r", "openrouter") == pytest.approx(0.5)


def test_reconcile_over_per_run_reports_breach_without_raising(tmp_path: Path) -> None:
    # The H19(b) case: reserve is under the ceiling (0.1 < 1.0) but the real cost is 5.0.
    guard = _guard(tmp_path, per_run={"openrouter": 1.0})
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.1)
    breaches = guard.reconcile(token, actual=5.0)
    run_breaches = [b for b in breaches if b.scope == "run"]
    assert len(run_breaches) == 1
    breach = run_breaches[0]
    assert isinstance(breach, BudgetBreach)
    assert breach.meter == "openrouter"
    assert breach.total == pytest.approx(5.0)
    assert breach.ceiling == pytest.approx(1.0)
    # Record-only: the actual is still durably recorded (the spend is not lost).
    assert guard.run_total("r", "openrouter") == pytest.approx(5.0)


def test_reconcile_over_per_day_reports_a_day_breach(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_day={"openrouter": 2.0})
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.1)
    breaches = guard.reconcile(token, actual=5.0)
    assert [b.scope for b in breaches] == ["day"]
    assert breaches[0].ceiling == pytest.approx(2.0)


def test_reconcile_over_both_reports_both_scopes(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 2.0})
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.1)
    breaches = guard.reconcile(token, actual=5.0)
    assert {b.scope for b in breaches} == {"run", "day"}


def test_release_reconcile_reports_no_breach(tmp_path: Path) -> None:
    guard = _guard(tmp_path, per_run={"openrouter": 1.0})
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.5)
    assert guard.reconcile(token, actual=0.0, note="released") == []


def test_meter_without_a_ceiling_reports_no_breach(tmp_path: Path) -> None:
    guard = _guard(tmp_path)  # no ceilings configured → unlimited
    token = guard.reserve(run_id="r", meter="openrouter", unit="usd", estimate=0.1)
    assert guard.reconcile(token, actual=999.0) == []


# --- consumer: record_cost emits a budget_breach event so the overshoot is visible ---------------


def _ctx(tmp: Path, *, per_run: dict[str, float]) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_run=per_run,
                estimates={"openrouter": 0.01},
            ),
        )
    )


def _events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    out: list[dict] = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def test_record_cost_emits_budget_breach_on_over_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _ctx(tmp_path, per_run={"openrouter": 1.0})
    token = ctx._budget_reserve("openrouter", "usd", estimate=0.01)  # under the ceiling
    ctx.record_cost("openrouter", "usd", 5.0, "test", token=token)  # real cost blows it
    breaches = [e for e in _events(capsys) if e.get("t") == "budget_breach"]
    assert len(breaches) == 1
    assert breaches[0]["meter"] == "openrouter"
    assert breaches[0]["scope"] == "run"
    assert breaches[0]["total"] == pytest.approx(5.0)
    assert breaches[0]["ceiling"] == pytest.approx(1.0)


def test_record_cost_within_ceiling_emits_no_budget_breach(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _ctx(tmp_path, per_run={"openrouter": 100.0})
    token = ctx._budget_reserve("openrouter", "usd", estimate=0.01)
    ctx.record_cost("openrouter", "usd", 0.5, "test", token=token)
    assert [e for e in _events(capsys) if e.get("t") == "budget_breach"] == []
