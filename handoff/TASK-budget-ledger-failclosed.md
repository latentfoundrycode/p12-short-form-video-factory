# TASK — budget ledger reads fail closed (H23) + atomic pre-flight refusal (H28)

## Why
**H23:** `BudgetGuard`'s read methods (`reserve`, `day_total`, `run_total`, all via `_snapshot`) re-read
the ledger. A complete, **valid-JSON** line whose `amount` is non-numeric (a bool, a string, a list)
parses fine but makes `_require_amount` raise a raw `ValueError`; a huge number raises `OverflowError`;
a read fault (`read_text` permission denied) raises `OSError`. These escape `reserve`/`day_total`/
`run_total` **un-wrapped**, so the runner's `_budget_reason` (which keys on `BudgetError`) mislabels the
refusal as a generic `failed`, and the atomic pre-flight (below) stalls on it. Every read method must
fail closed as `BudgetError`. (Non-JSON lines already raise `BudgetError` via `_read_ledger` — keep
that; this is the valid-JSON-bad-value and IO-fault gap.)

**H28:** `app/core/preflight.py::check_atomic_budget` calls `guard.run_total`/`guard.day_total` and
returns a refusal string or `None`. Once H23 makes those raise `BudgetError` on a poisoned ledger, the
pre-flight must **catch it and return a refusal string** — otherwise the `BudgetError` propagates out of
`run_request` (the call is not wrapped) after the request was already written `running`, stranding it.

Frozen RED contract is committed (HEAD): `tests/sdk/test_budget.py::
test_a_bad_amount_on_a_valid_json_line_fails_closed_as_budgeterror` (parametrized over reserve/
day_total/run_total × bad-amount types) and `tests/core/test_preflight.py::
test_check_atomic_budget_refuses_on_a_poisoned_ledger`.

## Changes (two files)

### 1. `sdk/sfvf/_budget.py` (H23)
- `_read_ledger`: it already converts `UnicodeDecodeError`/`JSONDecodeError`/non-dict to `BudgetError`.
  Add `OSError` (e.g. a `read_text` permission fault) to that conversion so a read fault is a
  `BudgetError`, not a raw `OSError`.
- `_snapshot` (the shared read path for `reserve`/`day_total`/`run_total`): wrap the
  `_token_states(_read_ledger(...))` call so a `ValueError`/`OverflowError` from parsing a poisoned
  amount becomes a `BudgetError`:
```python
    def _snapshot(self) -> dict[str, _TokenState]:
        try:
            return _token_states(_read_ledger(self._ledger_path))
        except (ValueError, OverflowError) as exc:
            raise BudgetError("budget ledger is unreadable") from exc
```
  (`_read_ledger` already raises `BudgetError` for its own faults; this catches the `_token_states`/
  `_require_amount` numeric faults. `read_run_spend` stays best-effort and is unaffected — it already
  catches `BudgetError`/`ValueError`/`OSError`/`OverflowError`.)
- Do NOT change `reconcile`'s own `_read_ledger` loop beyond the `OSError` addition above (it does not
  call `_require_amount`), and do NOT change `_require_amount`'s own `ValueError` (the `reserve(estimate=…)`
  and `reconcile(actual=…)` argument-validation tests rely on it raising `ValueError` for a bad ARGUMENT —
  that is the caller passing a bad value, distinct from a poisoned ledger).

### 2. `app/core/preflight.py` (H28)
In `check_atomic_budget`, read both totals for the meter under a `try` and turn a `BudgetError` into a
refusal string (so a ledger the guard cannot read refuses the run cleanly):
```python
    for meter, amount in estimate.per_meter.items():
        need = amount * safety_factor
        try:
            run_used = guard.run_total(run_id, meter)
            day_used = guard.day_total(meter)
        except BudgetError as exc:
            return f"budget ledger unreadable, refusing to start atomic run: {exc}"
        if meter in budget.per_run and need > budget.per_run[meter] - run_used:
            return f"estimated {meter} cost {need:g} exceeds per-run budget"
        if meter in budget.per_day and need > budget.per_day[meter] - day_used:
            return f"estimated {meter} cost {need:g} exceeds per-day budget"
    return None
```
Import `BudgetError` from `sfvf._budget`. Keep the message/None contract otherwise identical (the
existing headroom messages and the empty-estimate → None case must be byte-unchanged).

## Scope
Only `sdk/sfvf/_budget.py` and `app/core/preflight.py`. Do NOT change the runner's exit-code mapping,
`read_run_spend`, `_require_amount`'s argument validation, or the frozen tests. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_budget.py tests/core/test_preflight.py -q` → all pass
  (the new H23/H28 tests plus every existing budget/preflight test — the corrupt-line, torn-tail,
  bad-estimate, and bad-actual argument tests must stay green).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_budget_gate.py tests/sdk/test_budget_report.py -q` → still pass.
- `ruff check sdk app tests` and `ruff format --check sdk app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
- Also move H23 and H28 to the `## Resolved` section of `docs/HARDENING.md` (with this PR noted), since
  the ledger update rides the increment PR.
