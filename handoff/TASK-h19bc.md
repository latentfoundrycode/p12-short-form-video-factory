# TASK-h19bc — reconcile surfaces an after-the-fact ceiling breach (record-only)

## Goal

Close H19(b)/H20(c). `reserve` is the fail-closed pre-call gate, but a single UNDER-estimated call whose reconciled `actual` exceeds the ceiling is allowed after the fact (the money is already spent). For a multi-call run the next `reserve` denies, but for an ATOMIC single-call run there is no next reserve, so the overshoot is silent. Make `reconcile` RECORD the breach: after durably appending the `actual` line, re-check the reconciled per-run and per-day totals against the ceilings and RETURN the breaches. This is RECORD-ONLY — `reconcile` must NOT raise on a breach (the spend already happened; halting has no value and would break callers), though it still raises on a corrupt ledger or a bad amount as today. `Context.record_cost` emits a `budget_breach` event per breach so the overshoot is visible in the run record.

## Files to change

1. `sdk/sfvf/_budget.py`
2. `sdk/sfvf/context.py`

Do not touch any test or any other module. Frozen contract: `tests/sdk/test_budget_breach.py`.

## The change

### 1. `_budget.py` — a breach type and reconcile's return

- Add a frozen dataclass `BudgetBreach` with fields `meter: str`, `scope: str` (either `"run"` or `"day"`), `total: float`, `ceiling: float`. Place it near `Ceilings`.
- Change `reconcile(self, token, *, actual, note="")` to return `list[BudgetBreach]` (empty when no breach). Keep everything it does today (the `_snapshot()` fail-closed check, reading the reserved line for `run_id`/`workflow_id`/`meter`/`unit`, appending the `actual` line — all unchanged and still first, so the spend is recorded before any breach check and a corrupt ledger / bad amount still raises exactly as now). THEN, after the append, if a `meter` was resolved from the token: take a fresh `states = self._snapshot()`, compute `run_total = _run_sum(states, run_id, meter, workflow_id)` and `day_total = _day_sum(states, meter, today)` (with `today = self._now().astimezone(UTC).date()`, as `reserve` does), and build the result list: append `BudgetBreach(meter, "run", run_total, float(ceiling))` when `meter in self._ceilings.per_run` and the run total exceeds that ceiling, and likewise `BudgetBreach(meter, "day", day_total, float(ceiling))` for `per_day`. Report a breach only for a USABLE finite numeric ceiling that is genuinely exceeded (`total > ceiling`) — do NOT report a breach merely because a ceiling is unusable/non-finite (that path is already denied at `reserve`). Return `[]` when the token had no reserved line (empty `meter`), on a release/`actual=0.0` that stays within ceiling, and for a meter with no configured ceiling.

Order matters: the `actual` line is appended BEFORE the breach snapshot so the reconciled totals include this call's real cost. Never raise because of a breach.

### 2. `context.py` — surface the breach as an event

- `_budget_reconcile(self, token, *, actual, note="")` currently returns `None` and calls `guard.reconcile(...)`. Return the breaches it produces: `return self._budget_guard(cfg).reconcile(token, actual=actual, note=note)` when a guard runs, and `[]` (empty list) on the no-op paths (`token is None or cfg is None`). Update its return type to `list[BudgetBreach]` (import `BudgetBreach` from `._budget`).
- `record_cost(...)` currently emits the `cost` event then calls `self._budget_reconcile(token, actual=...)`. Capture its return and, for each `BudgetBreach`, emit a `budget_breach` event AFTER the cost event: `self.emit({"t": "budget_breach", "meter": b.meter, "scope": b.scope, "total": b.total, "ceiling": b.ceiling})`. Emit nothing when the list is empty.
- The `_budget_reserved` context manager's except-path call to `_budget_reconcile(token, actual=0.0, note="released")` can ignore the returned list (a release stays within ceiling) — leave its behaviour unchanged.

## Constraints

- RECORD-ONLY: no new raise, no run halt. `reconcile` returning a list instead of `None` is backward-compatible for the one caller (`_budget_reconcile`) which you are updating; no other caller exists.
- The existing budget contracts must stay green: `tests/sdk/test_budget.py`, `tests/core/test_forecast_recording.py`, `tests/sdk/test_cost_events.py`, and the integration budget tests. Reconcile's existing side effects (snapshot fail-closed, actual append, last-write-wins) are unchanged.
- No new dependency. One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/sdk/test_budget_breach.py` is fully green (it fails to import now — `BudgetBreach` is the new symbol).
- The budget/cost/forecast suites above stay green.
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for Bridge Feedback; record any defect/pitfall learning there too, for the Issues file.
