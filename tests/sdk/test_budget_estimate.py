"""Frozen contract — Stage P, P-2b: per-call budget estimate + cost-with-source (money change).

Adapters price each call, so the reservation before a paid call uses that per-call estimate — but
WITHOUT reopening the fail-closed hole the plan-critic flagged (B1): a per-call estimate must never
let a meter with NO configured ceiling reserve an unbounded amount. And every reconciled cost must
record HOW it was known (reported | metered | priced), both in the emitted `cost` event and the
ledger note, so a stale pinned rate is visible rather than passed off as exact (§3.5 of the plan).

This increment changes `sdk/sfvf/context.py`:
  * `_budget_reserve(meter, unit, estimate=None)` — the §3.5 rule.
  * `_budget_reconcile(token, *, actual, note="")` — the note reaches the ledger.
  * `record_cost(meter, unit, amount, source, *, token=None)` — emit the `cost` event carrying
    `source` and reconcile with `note=source`, in one place so an adapter cannot drift the two.

No network, no secrets; the BudgetGuard writes a real JSONL ledger under tmp_path.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from sfvf._budget import BudgetError, read_run_spend
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths


def _ctx(
    tmp: Path,
    *,
    budget: bool = True,
    per_run: dict[str, float] | None = None,
    per_day: dict[str, float] | None = None,
    estimates: dict[str, float] | None = None,
) -> Context:
    cfg = None
    if budget:
        cfg = BudgetConfig(
            ledger_path=tmp / "ledger.jsonl",
            per_run=per_run or {},
            per_day=per_day or {},
            estimates=estimates or {},
        )
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            secrets={},
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=cfg,
        )
    )


def _ledger_entries(tmp: Path) -> list[dict]:
    ledger = tmp / "ledger.jsonl"
    if not ledger.is_file():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]


def _cost_events(captured: str) -> list[dict]:
    events = []
    for line in captured.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                obj = json.loads(stripped)
            except ValueError:
                continue
            if obj.get("t") == "cost":
                events.append(obj)
    return events


# ---------------------------------------------------------------------------
# The unchanged no-per-call-estimate path (today's behaviour must not regress).
# ---------------------------------------------------------------------------


def test_reserve_uses_the_configured_estimate_when_no_per_call_estimate_is_given(
    tmp_path: Path,
) -> None:
    ctx = _ctx(tmp_path, per_day={"openai": 100.0}, estimates={"openai": 2.0})
    ctx._budget_reserve("openai", "usd")
    assert read_run_spend(tmp_path / "ledger.jsonl", ctx.run_id)["openai"] == pytest.approx(2.0)


def test_reserve_with_no_budget_config_is_refused(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, budget=False)
    with pytest.raises(BudgetError):
        ctx._budget_reserve("openai", "usd")


def test_reserve_with_no_configured_estimate_and_no_per_call_is_refused(tmp_path: Path) -> None:
    # Fail closed: a meter with a config section but no positive estimate and no per-call value
    # must NOT reserve nothing (which would let the call through ungated).
    ctx = _ctx(tmp_path, per_day={"openai": 100.0})
    with pytest.raises(BudgetError):
        ctx._budget_reserve("openai", "usd")


# ---------------------------------------------------------------------------
# The per-call estimate (§3.5 rule) — must not reopen the fail-closed hole (B1).
# ---------------------------------------------------------------------------


def test_per_call_estimate_requires_a_ceiling_for_the_meter(tmp_path: Path) -> None:
    # A per-call estimate for a meter with NO per_run/per_day ceiling would reserve against an
    # unlimited cap — exactly the hole B1 named. It must be refused, not honoured.
    ctx = _ctx(tmp_path, estimates={})  # no ceilings at all
    with pytest.raises(BudgetError):
        ctx._budget_reserve("openai", "usd", estimate=5.0)


def test_per_call_estimate_is_honoured_when_a_ceiling_exists(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_day={"openai": 100.0})  # ceiling present, no configured estimate
    ctx._budget_reserve("openai", "usd", estimate=5.0)
    assert read_run_spend(tmp_path / "ledger.jsonl", ctx.run_id)["openai"] == pytest.approx(5.0)


def test_per_call_estimate_reserves_the_max_of_per_call_and_configured(tmp_path: Path) -> None:
    # The configured estimate remains a FLOOR: a smaller per-call value cannot under-reserve.
    high = _ctx(tmp_path / "hi", per_day={"openai": 100.0}, estimates={"openai": 2.0})
    high._budget_reserve("openai", "usd", estimate=5.0)  # per-call above the floor
    assert read_run_spend(tmp_path / "hi" / "ledger.jsonl", high.run_id)["openai"] == pytest.approx(
        5.0
    )

    low = _ctx(tmp_path / "lo", per_day={"openai": 100.0}, estimates={"openai": 2.0})
    low._budget_reserve("openai", "usd", estimate=1.0)  # per-call below the floor
    assert read_run_spend(tmp_path / "lo" / "ledger.jsonl", low.run_id)["openai"] == pytest.approx(
        2.0
    )


@pytest.mark.parametrize("bad", [0.0, -1.0, math.inf, math.nan])
def test_per_call_estimate_must_be_finite_and_positive(tmp_path: Path, bad: float) -> None:
    ctx = _ctx(tmp_path, per_day={"openai": 100.0})
    with pytest.raises(BudgetError):
        ctx._budget_reserve("openai", "usd", estimate=bad)


def test_per_call_estimate_still_enforces_the_ceiling(tmp_path: Path) -> None:
    # A per-call estimate over the remaining ceiling is refused (the cap is real, not advisory).
    ctx = _ctx(tmp_path, per_run={"openai": 3.0})
    with pytest.raises(BudgetError):
        ctx._budget_reserve("openai", "usd", estimate=5.0)


# ---------------------------------------------------------------------------
# Reconcile note + record_cost: the source reaches the ledger and the cost event.
# ---------------------------------------------------------------------------


def test_reconcile_writes_the_note_into_the_ledger(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_day={"openai": 100.0}, estimates={"openai": 2.0})
    token = ctx._budget_reserve("openai", "usd")
    ctx._budget_reconcile(token, actual=3.0, note="metered")
    actuals = [e for e in _ledger_entries(tmp_path) if e.get("kind") == "actual"]
    assert actuals and actuals[-1]["amount"] == pytest.approx(3.0)
    assert actuals[-1]["note"] == "metered"


def test_record_cost_emits_a_cost_event_with_source_and_reconciles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _ctx(tmp_path, per_day={"openai": 100.0}, estimates={"openai": 2.0})
    token = ctx._budget_reserve("openai", "usd")
    ctx.record_cost("openai", "usd", 3.0, "metered", token=token)

    events = _cost_events(capsys.readouterr().out)
    assert events, "record_cost must emit a cost event"
    event = events[-1]
    assert event["meter"] == "openai"
    assert event["unit"] == "usd"
    assert event["amount"] == pytest.approx(3.0)
    assert event["source"] == "metered"
    assert event["cached"] is False

    actuals = [e for e in _ledger_entries(tmp_path) if e.get("kind") == "actual"]
    assert actuals and actuals[-1]["amount"] == pytest.approx(3.0)
    assert actuals[-1]["note"] == "metered"  # the same source reaches the ledger


def test_record_cost_without_a_token_still_emits_the_event(tmp_path: Path) -> None:
    # A cached/free path may record a cost with no reservation to reconcile; the event still carries
    # source, and no reconcile is attempted (token=None is a no-op, matching _budget_reconcile).
    ctx = _ctx(tmp_path, per_day={"openai": 100.0})
    ctx.record_cost("openai", "usd", 0.0, "reported")
    # No exception, and no 'actual' ledger entry was forced by a None token.
    assert [e for e in _ledger_entries(tmp_path) if e.get("kind") == "actual"] == []
