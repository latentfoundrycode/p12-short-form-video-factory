# TASK — budget ledger fail-closed, COMPLETION (H23 reconcile path)

## Why (round 3)
Cross-family review found the last unvalidated public ledger read: `reconcile()` reads the
ledger with its OWN loop (to recover the token's `run_id`/`meter`/`unit`) and never validates
amounts, so a valid-JSON `reserved` line with a non-numeric `amount` lets
`reconcile("t1", actual=0.25)` append an `actual` and return successfully instead of raising
`BudgetError`. Every other public method (`reserve` via `_snapshot` ceiling checks,
`day_total`, `run_total`) already fails closed through `_snapshot`; `reconcile` must too, so a
poisoned ledger is uniformly refused rather than silently written to.

Frozen RED test (committed): `test_reconcile_fails_closed_on_a_poisoned_ledger` in
`tests/sdk/test_budget.py` — a `reserved` line with token `"t1"` and amount `"not-a-number"`,
then `guard.reconcile("t1", actual=0.25)` must raise `BudgetError`.

## Change — only in `sdk/sfvf/_budget.py`, method `reconcile`
Validate the ledger through the already-fail-closed `_snapshot()` BEFORE the token lookup and
append. `_snapshot()` reads + validates every line and raises `BudgetError` on any corruption
(bad amount via its `except (ValueError, OverflowError)` wrap, token-less spend line via H59,
IO/JSON via `_read_ledger`). Keep the existing loop for `run_id`/`meter`/`unit` (a
`_TokenState` does not carry `unit`, so the loop stays):

```python
    def reconcile(self, token: str, *, actual: float, note: str = "") -> None:
        with self._held():
            amount = _require_amount(actual)
            self._snapshot()  # fail closed on a corrupt ledger before appending (H23)
            run_id = ""
            meter = ""
            unit = ""
            for entry in _read_ledger(self._ledger_path):
                if entry.get("kind") == "reserved" and entry.get("token") == token:
                    run_id = _as_str(entry.get("run_id"))
                    meter = _as_str(entry.get("meter"))
                    unit = _as_str(entry.get("unit"))
                    break
            _append_line(
                self._ledger_path,
                self._record(
                    token=token,
                    run_id=run_id,
                    meter=meter,
                    unit=unit,
                    amount=amount,
                    kind="actual",
                    note=note,
                ),
            )
```

`_require_amount(actual)` stays first: a bad ARGUMENT (`reconcile(actual=NaN/inf)`) is a caller
error and must still raise `ValueError`, distinct from ledger corruption. `self._snapshot()` is
called for its validation side effect only (its return value is unused here); the double read
under the held lock is acceptable — `reconcile` is not a hot path.

## Scope
ONLY `reconcile` in `sdk/sfvf/_budget.py`. Do NOT touch `_require_amount`, `_snapshot`,
`_read_ledger`, `_token_states`, `_append_line`, `check_atomic_budget`, `read_run_spend`, or any
test. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_budget.py tests/core/test_preflight.py tests/integration/test_budget_gate.py tests/sdk/test_budget_report.py -q` → all pass (the new `reconcile` fail-closed test plus every prior budget/preflight test — the bad-ARGUMENT tests `reconcile(actual=NaN)`/`reserve(estimate=…)` must stay `ValueError`, the corrupt-line/torn-tail/concurrency tests must stay green).
- `ruff check sdk tests` and `ruff format --check sdk tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
