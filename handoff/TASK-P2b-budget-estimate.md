# TASK — P-2b: per-call budget estimate + cost-with-source (money change)

## Goal (one sentence)
Change `sdk/sfvf/context.py` so a paid call can reserve its own per-call estimate (without reopening the
fail-closed hole), reconcile with a note, and record a `cost` event that carries how the amount was known.

## Spec (docs/PROVIDER_LAYER_PLAN.md §3.5; plan-critic B1/S1) — authoritative
Adapters price each call, so the reservation must be able to use that per-call figure. But a per-call
estimate must NEVER let a meter with no ceiling reserve an unbounded amount (the `BudgetGuard` treats a
meter absent from `per_run`/`per_day` as unlimited — that is exactly hole B1). And every reconciled cost
must record its `source` (`reported | metered | priced`) in both the `cost` event and the ledger note.

## Frozen contract (already committed — do NOT edit)
`tests/sdk/test_budget_estimate.py`. Make all of it pass; the full suite (esp. `test_budget*.py`,
`test_cost_recording.py`, the mocked provider/agents tests) must stay green.

## What to change — ONLY `sdk/sfvf/context.py`

### 1. `_budget_reserve(self, meter, unit, estimate=None)`
Add the optional `estimate: float | None = None` parameter. Keep the current `cfg is None → BudgetError`.
Then:
```python
has_ceiling = meter in cfg.per_run or meter in cfg.per_day
configured = cfg.estimates.get(meter)
if estimate is not None:
    # per-call estimate path (B1): only with a real ceiling, only finite & > 0.
    if isinstance(estimate, bool) or not isinstance(estimate, int | float) \
            or not math.isfinite(estimate) or estimate <= 0:
        raise BudgetError(f"per-call estimate for meter {meter!r} must be finite and > 0")
    if not has_ceiling:
        raise BudgetError(
            f"per-call estimate for meter {meter!r} needs a configured per_run/per_day ceiling"
        )
    reserve_amount = estimate
    if configured is not None and configured > 0:
        reserve_amount = max(estimate, configured)   # configured estimate stays a FLOOR
else:
    # unchanged path: require a positive configured estimate (fail closed otherwise).
    if configured is None or not (configured > 0):
        raise BudgetError(f"no positive budget estimate configured for meter {meter!r}")
    reserve_amount = configured
guard = self._budget_guard(cfg)
return guard.reserve(run_id=self.run_id, meter=meter, unit=unit, estimate=reserve_amount)
```
`math` is needed — add `import math` at the top of the module if it is not already imported.

### 2. `_budget_reconcile(self, token, *, actual, note="")`
Add `note: str = ""` and pass it through: `...reconcile(token, actual=actual, note=note)`.
(`BudgetGuard.reconcile` already accepts `note`.) The `token is None or cfg is None → return` no-op stays.

### 3. `record_cost(self, meter, unit, amount, source, *, token=None)` (new method)
One place that both emits the cost event and reconciles, so an adapter cannot let the two disagree:
```python
def record_cost(self, meter: str, unit: str, amount: float, source: str,
                *, token: str | None = None) -> None:
    self.emit({"t": "cost", "meter": meter, "unit": unit, "amount": amount,
               "source": source, "cached": False})
    self._budget_reconcile(token, actual=amount, note=source)
```
`token=None` means no reservation to reconcile (a cached/free record) — the event is still emitted.

## Constraints / do-nots
- Touch ONLY `sdk/sfvf/context.py`. Do NOT edit any test, `sdk/sfvf/agents.py`, `sdk/sfvf/_budget.py`,
  or anything else. Backward compatibility matters: existing callers use `_budget_reserve(meter, unit)`
  and `_budget_reconcile(token, actual=...)` with no new args — those must keep working unchanged.
- No `app.*` import, no new dependency.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/context.py`

## Verify (from the worktree; set `PYTHONPATH` to the worktree `sdk`)
- `-m pytest tests/sdk/test_budget_estimate.py -q` → all pass.
- `-m pytest tests/sdk/test_budget.py tests/sdk/test_budget_report.py tests/core/test_cost_recording.py -q`
  → still green (no regression to the existing budget/cost paths).
- `-m pytest -q` (full) → green apart from the pre-existing HyperFrames/chrome env failures.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
