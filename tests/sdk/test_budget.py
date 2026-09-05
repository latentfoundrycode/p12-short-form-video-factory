"""T2a contract: the budget circuit-breaker engine (`sfvf._budget`).

The minimal money-safety backstop that must exist BEFORE any live paid call (Architecture §5.4,
reserve-then-reconcile, restricted to the safety subset — full per-provider metering/forecasts are
Stage C). It is a pure, file-backed engine with NO wiring into the agents/video call paths yet.

Model:
- A JSONL **ledger** file records one entry per reservation and per reconciliation. The file is the
  durable, cross-process source of truth (parent surfaces it; child enforces against it).
- `reserve(...)` is called BEFORE a priced call: it checks the kill-switch and the per-run and
  per-day ceilings, and — only if the prospective charge fits — appends a `reserved` entry and
  returns a token. A reservation is visible to concurrent reservers immediately, so several steps
  cannot each see the full remaining balance and overshoot together.
- `reconcile(token, actual=...)` is called AFTER the call with the real amount; the reserved
  estimate is then superseded by the actual for all totals.
- Ceilings are per-meter (a meter is a provider id such as "openrouter"); units are never combined
  across meters. A meter absent from a ceiling map is unlimited.
- Totals: `day_total(meter)` counts today's entries (UTC calendar day of the injected clock);
  `run_total(run_id, meter)` counts one run's entries. For each token the effective amount is the
  reconciled actual if present, else the open reserved estimate (never both).

Fake ceilings/paths live only under tmp_path; no real spend, no network.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf._budget import (
    BudgetExceededError,
    BudgetGuard,
    Ceilings,
    KillSwitchEngagedError,
)


def _fixed_clock(moment: datetime):
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
    kill_switch: Path | None = None,
    moment: datetime | None = None,
) -> BudgetGuard:
    return BudgetGuard(
        tmp_path / "ledger.jsonl",
        ceilings=Ceilings(per_run=per_run or {}, per_day=per_day or {}),
        kill_switch_path=kill_switch,
        now=_fixed_clock(moment or datetime(2026, 9, 5, 12, 0, tzinfo=UTC)),
    )


# --- reservations, totals, reconciliation ---


def test_reserve_under_ceiling_returns_token_and_appends_entry(tmp_path: Path):
    guard = _guard(tmp_path, per_run={"openrouter": 2.0}, per_day={"openrouter": 10.0})
    token = guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.5)
    assert isinstance(token, str) and token
    entries = _ledger_lines(tmp_path / "ledger.jsonl")
    assert len(entries) == 1
    assert entries[0]["meter"] == "openrouter"
    assert entries[0]["kind"] == "reserved"
    assert entries[0]["amount"] == 0.5
    assert entries[0]["run_id"] == "r1"


def test_missing_ledger_totals_are_zero(tmp_path: Path):
    guard = _guard(tmp_path)
    assert guard.day_total("openrouter") == 0.0
    assert guard.run_total("r1", "openrouter") == 0.0


def test_reserve_counts_toward_run_and_day_totals(tmp_path: Path):
    guard = _guard(tmp_path, per_run={"openrouter": 5.0}, per_day={"openrouter": 5.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=1.0)
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.5)
    assert guard.day_total("openrouter") == pytest.approx(1.5)
    assert guard.run_total("r1", "openrouter") == pytest.approx(1.5)


def test_reconcile_supersedes_reserved_estimate(tmp_path: Path):
    guard = _guard(tmp_path, per_day={"openrouter": 10.0})
    token = guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=2.0)
    guard.reconcile(token, actual=0.75)
    # The open reservation is closed; only the actual counts (no double-counting).
    assert guard.day_total("openrouter") == pytest.approx(0.75)
    assert guard.run_total("r1", "openrouter") == pytest.approx(0.75)


# --- ceilings ---


def test_reserve_breaching_per_run_ceiling_raises_and_appends_nothing(tmp_path: Path):
    guard = _guard(tmp_path, per_run={"openrouter": 1.0}, per_day={"openrouter": 100.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.8)
    before = _ledger_lines(tmp_path / "ledger.jsonl")
    with pytest.raises(BudgetExceededError):
        guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.5)  # 0.8+0.5 > 1.0
    # A denied reservation must not be recorded.
    assert _ledger_lines(tmp_path / "ledger.jsonl") == before


def test_reserve_breaching_per_day_ceiling_raises(tmp_path: Path):
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 1.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.7)
    with pytest.raises(BudgetExceededError):
        # across runs, same day
        guard.reserve(run_id="r2", meter="openrouter", unit="EUR", estimate=0.5)


def test_reservation_is_visible_to_concurrent_reserver(tmp_path: Path):
    # Two open reservations (no reconcile) both count, so the second reserver cannot overshoot.
    guard = _guard(tmp_path, per_day={"openrouter": 1.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.6)
    with pytest.raises(BudgetExceededError):
        guard.reserve(run_id="r2", meter="openrouter", unit="EUR", estimate=0.6)  # 0.6+0.6 > 1.0


def test_meter_ceilings_are_isolated(tmp_path: Path):
    # A meter absent from the ceiling map is unlimited; one meter's spend never limits another.
    guard = _guard(tmp_path, per_day={"openrouter": 1.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.9)
    # higgsfield has no ceiling → allowed regardless of amount
    guard.reserve(run_id="r1", meter="higgsfield", unit="credits", estimate=500.0)
    assert guard.day_total("higgsfield") == pytest.approx(500.0)


def test_exact_ceiling_is_allowed_overshoot_is_denied(tmp_path: Path):
    guard = _guard(tmp_path, per_run={"openrouter": 1.0})
    # exactly at ceiling: allowed
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=1.0)
    with pytest.raises(BudgetExceededError):
        guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.01)


# --- kill switch ---


def test_kill_switch_blocks_all_reservations(tmp_path: Path):
    ks = tmp_path / "STOP"
    ks.write_text("halt", encoding="utf-8")
    guard = _guard(tmp_path, per_day={"openrouter": 1000.0}, kill_switch=ks)
    with pytest.raises(KillSwitchEngagedError):
        guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.01)
    assert _ledger_lines(tmp_path / "ledger.jsonl") == []


def test_no_kill_switch_path_means_never_engaged(tmp_path: Path):
    guard = _guard(tmp_path, per_day={"openrouter": 1.0}, kill_switch=tmp_path / "absent")
    # absent file → not engaged; ordinary ceiling logic applies
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.5)


# --- day boundary ---


def test_prior_day_entries_do_not_count_today(tmp_path: Path):
    yesterday = _guard(
        tmp_path, per_day={"openrouter": 10.0}, moment=datetime(2026, 9, 4, 23, 0, tzinfo=UTC)
    )
    yesterday.reserve(run_id="r0", meter="openrouter", unit="EUR", estimate=9.0)
    today = _guard(
        tmp_path, per_day={"openrouter": 10.0}, moment=datetime(2026, 9, 5, 1, 0, tzinfo=UTC)
    )
    # Yesterday's 9.0 must not count toward today's day ceiling.
    assert today.day_total("openrouter") == pytest.approx(0.0)
    # fits today's fresh 10.0
    today.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=9.5)


# --- hostile input must not defeat the guard ---


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, -0.5])
def test_reserve_rejects_non_finite_or_negative_estimate(tmp_path: Path, bad: float):
    # A NaN/inf estimate would slip past every `estimate > ceiling` check (NaN compares False)
    # and poison all later totals; a negative estimate is nonsense. Both must be refused and must
    # append nothing, so the money guard cannot be defeated by a bad estimate.
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    with pytest.raises(ValueError):
        guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=bad)
    assert _ledger_lines(tmp_path / "ledger.jsonl") == []


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_reconcile_rejects_non_finite_actual(tmp_path: Path, bad: float):
    # A non-finite actual would likewise poison totals. Reject it; the prior reservation stays.
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.5)
    before = _ledger_lines(tmp_path / "ledger.jsonl")
    with pytest.raises(ValueError):
        guard.reconcile(before[0]["token"], actual=bad)
    assert _ledger_lines(tmp_path / "ledger.jsonl") == before
