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
    BudgetError,
    BudgetExceededError,
    BudgetGuard,
    Ceilings,
    KillSwitchEngagedError,
    read_run_spend,
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


# --- ledger integrity: a corrupt ledger must fail closed, a torn tail must be tolerated ---


def test_corrupt_ledger_line_fails_closed(tmp_path: Path):
    # A complete-but-unparseable ledger line means real corruption. Silently skipping it would
    # under-count spend and let a run overshoot, so the guard must refuse (fail closed) instead.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text("this is not json\n", encoding="utf-8")
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})
    with pytest.raises(BudgetError):
        guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.1)


def test_torn_tail_line_is_tolerated(tmp_path: Path):
    # A crash mid-append leaves a final line with no trailing newline; that write never completed
    # and never handed back a token, so only that tail is dropped — earlier entries still count.
    ledger = tmp_path / "ledger.jsonl"
    good = {
        "ts": "2026-09-05T10:00:00Z",
        "token": "t1",
        "run_id": "r1",
        "meter": "openrouter",
        "unit": "EUR",
        "amount": 0.4,
        "kind": "reserved",
        "note": "",
    }
    ledger.write_text(
        json.dumps(good) + "\n" + '{"ts": "2026-09-05T10:00:01Z", "tok', encoding="utf-8"
    )
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})
    assert guard.day_total("openrouter") == pytest.approx(
        0.4
    )  # torn tail dropped, good line counts
    guard.reserve(run_id="r1", meter="openrouter", unit="EUR", estimate=0.1)  # append still works


def test_lock_path_is_canonical_across_spellings(tmp_path: Path):
    # Two guards addressing the same ledger via different path spellings must share one lock file,
    # or concurrent appends from each would not serialize.
    sub = tmp_path / "sub"
    sub.mkdir()
    direct = _guard(sub, per_day={"openrouter": 1.0})
    spelled = BudgetGuard(
        tmp_path / "sub" / ".." / "sub" / "ledger.jsonl",
        ceilings=Ceilings(per_run={}, per_day={"openrouter": 1.0}),
        now=_fixed_clock(datetime(2026, 9, 5, 12, 0, tzinfo=UTC)),
    )
    assert direct._lock_path == spelled._lock_path
    assert direct._ledger_path == spelled._ledger_path


def test_kill_switch_path_is_canonicalized(tmp_path: Path):
    # The emergency stop must not fail open: a relative kill-switch path would stop matching after a
    # chdir. The guard must canonicalize it at construction so it is checked at a stable location.
    guard = BudgetGuard(
        tmp_path / "ledger.jsonl",
        ceilings=Ceilings(per_run={}, per_day={}),
        kill_switch_path=Path("relative") / ".." / "relative" / "STOP",
        now=_fixed_clock(datetime(2026, 9, 5, 12, 0, tzinfo=UTC)),
    )
    assert guard._kill_switch_path is not None
    assert guard._kill_switch_path.is_absolute()
    assert guard._kill_switch_path == (Path("relative") / ".." / "relative" / "STOP").resolve()


# --- H23: every read method fails closed as BudgetError on a poisoned (valid-JSON) ledger ---------


def _reserved_line(amount: object, *, meter: str = "openrouter") -> dict:
    return {
        "ts": "2026-09-05T10:00:00Z",
        "token": "t1",
        "run_id": "r1",
        "meter": meter,
        "unit": "EUR",
        "amount": amount,
        "kind": "reserved",
        "note": "",
    }


@pytest.mark.parametrize("bad_amount", ["not-a-number", True, [1]])
@pytest.mark.parametrize("method", ["reserve", "day_total", "run_total"])
def test_a_bad_amount_on_a_valid_json_line_fails_closed_as_budgeterror(
    tmp_path: Path, method: str, bad_amount: object
) -> None:
    # H23: a complete, VALID-JSON ledger line whose `amount` is non-numeric parses fine but poisons
    # `_require_amount`. Today that raises a raw ValueError/OverflowError out of reserve/day_total/
    # run_total — which the runner mislabels (not a budget stop) and which stalls the atomic
    # pre-flight (H28). Every read method must instead fail closed as BudgetError.
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(_reserved_line(bad_amount)) + "\n", encoding="utf-8")
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    with pytest.raises(BudgetError):
        if method == "reserve":
            guard.reserve(run_id="r2", meter="openrouter", unit="EUR", estimate=0.1)
        elif method == "day_total":
            guard.day_total("openrouter")
        else:
            guard.run_total("r1", "openrouter")


# --- H23 completeness: every ledger filesystem/integrity fault fails closed as BudgetError ---


def test_a_stat_oserror_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # `_read_ledger` calls `path.is_file()` outside its try; a stat PermissionError must still fail
    # closed as BudgetError, not escape raw (which check_atomic_budget cannot catch → stranded run).
    (tmp_path / "ledger.jsonl").write_text("", encoding="utf-8")
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})

    def boom_is_file(self: Path) -> bool:
        raise PermissionError("stat denied")

    monkeypatch.setattr(Path, "is_file", boom_is_file)
    with pytest.raises(BudgetError):
        guard.day_total("openrouter")


def test_a_lock_acquisition_oserror_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The interprocess lock acquired by every read/write method can leak an OSError (open / msvcrt /
    # fcntl fault); it must be converted to BudgetError so the guard is uniformly fail-closed.
    import sfvf._budget as budget_mod

    guard = _guard(tmp_path, per_day={"openrouter": 100.0})

    def boom_lock(handle: object) -> None:
        raise OSError("lock unavailable")

    monkeypatch.setattr(budget_mod, "_lock_exclusive", boom_lock)
    with pytest.raises(BudgetError):
        guard.day_total("openrouter")


def test_a_spend_record_missing_its_token_fails_closed(tmp_path: Path) -> None:
    # A reserved/actual ledger line carrying an `amount` but no token is corruption (the engine
    # writes a token). Silently skipping it under-counts spend and lets a run overshoot, so it must
    # fail closed rather than lower the total.
    line = {
        "ts": "2026-09-05T10:00:00Z",
        "run_id": "r1",
        "meter": "openrouter",
        "unit": "EUR",
        "amount": 0.5,
        "kind": "reserved",
        "note": "",
    }
    (tmp_path / "ledger.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})
    with pytest.raises(BudgetError):
        guard.day_total("openrouter")


def test_reconcile_fails_closed_on_a_poisoned_ledger(tmp_path: Path) -> None:
    # reconcile() reads the ledger (its own loop) to find the token's meter/unit, bypassing the
    # validated _snapshot path. A valid-JSON reserved line with a non-numeric amount must make
    # reconcile fail closed too — not silently append an `actual` to a corrupt ledger.
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps(_reserved_line("not-a-number")) + "\n", encoding="utf-8"
    )
    guard = _guard(tmp_path, per_day={"openrouter": 100.0})
    with pytest.raises(BudgetError):
        guard.reconcile("t1", actual=0.25)


# --- H22: ledger isolation by workflow_id (a run_id is only per-workflow-unique) ---


def test_run_total_isolates_two_workflows_sharing_a_run_id(tmp_path: Path) -> None:
    # H22: two DIFFERENT workflows started in the same UTC second get the same run_id. The ledger
    # is machine-wide; run_total must key by (run_id, workflow_id, meter) so their spend does not
    # merge and over-count each other's per-run ceiling.
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    guard.reserve(
        run_id="20260923-171500", workflow_id="wfA", meter="openrouter", unit="usd", estimate=1.0
    )
    guard.reserve(
        run_id="20260923-171500", workflow_id="wfB", meter="openrouter", unit="usd", estimate=2.0
    )
    assert guard.run_total("20260923-171500", "openrouter", workflow_id="wfA") == pytest.approx(1.0)
    assert guard.run_total("20260923-171500", "openrouter", workflow_id="wfB") == pytest.approx(2.0)


def test_read_run_spend_isolates_two_workflows_sharing_a_run_id(tmp_path: Path) -> None:
    # H22: read_run_spend must mirror the gate's filter — key by workflow_id too — so per-run
    # reporting does not cross-report a same-run_id sibling workflow's spend.
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    guard.reserve(
        run_id="20260923-171500", workflow_id="wfA", meter="openrouter", unit="usd", estimate=1.0
    )
    guard.reserve(
        run_id="20260923-171500", workflow_id="wfB", meter="openrouter", unit="usd", estimate=2.0
    )
    ledger = tmp_path / "ledger.jsonl"
    assert read_run_spend(ledger, "20260923-171500", workflow_id="wfA") == {"openrouter": 1.0}
    assert read_run_spend(ledger, "20260923-171500", workflow_id="wfB") == {"openrouter": 2.0}


def test_reconcile_preserves_workflow_id_isolation(tmp_path: Path) -> None:
    # H22: reconcile recovers the reserved line's workflow_id (by token) and writes it on the
    # actual, so the reconciled spend stays in its own workflow's namespace.
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    token_a = guard.reserve(
        run_id="20260923-171500", workflow_id="wfA", meter="openrouter", unit="usd", estimate=1.0
    )
    guard.reserve(
        run_id="20260923-171500", workflow_id="wfB", meter="openrouter", unit="usd", estimate=2.0
    )
    guard.reconcile(token_a, actual=0.5)
    assert guard.run_total("20260923-171500", "openrouter", workflow_id="wfA") == pytest.approx(0.5)
    assert guard.run_total("20260923-171500", "openrouter", workflow_id="wfB") == pytest.approx(2.0)


def test_legacy_ledger_line_without_workflow_id_totals_in_the_default_namespace(
    tmp_path: Path,
) -> None:
    # Backward compatibility: a durable ledger written before H22 has no workflow_id field. Those
    # lines must still count under the default ("") namespace, not fail closed — the field is new.
    (tmp_path / "ledger.jsonl").write_text(json.dumps(_reserved_line(1.5)) + "\n", encoding="utf-8")
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    assert guard.run_total("r1", "openrouter") == pytest.approx(1.5)
    assert guard.run_total("r1", "openrouter", workflow_id="") == pytest.approx(1.5)


# --- H60: a non-string meter on a spend line fails closed (uniform with token/amount) ---


@pytest.mark.parametrize("bad_meter", [123, True, ["openrouter"], None])
@pytest.mark.parametrize("kind", ["reserved", "actual"])
def test_a_non_string_meter_on_a_spend_line_fails_closed(
    tmp_path: Path, kind: str, bad_meter: object
) -> None:
    # H60: a valid-JSON reserved/actual line whose `meter` is present but not a usable string
    # currently drops out of _run_sum/_day_sum (silent under-count). The engine always writes a
    # string meter, so a non-string meter is corruption and must fail closed as BudgetError,
    # uniform with the missing-token (H59) and bad-amount (H23) checks.
    line = _reserved_line(1.0)
    line["kind"] = kind
    line["meter"] = bad_meter
    (tmp_path / "ledger.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    guard = _guard(tmp_path, per_run={"openrouter": 100.0}, per_day={"openrouter": 100.0})
    with pytest.raises(BudgetError):
        guard.day_total("openrouter")
    with pytest.raises(BudgetError):
        guard.run_total("r1", "openrouter")
