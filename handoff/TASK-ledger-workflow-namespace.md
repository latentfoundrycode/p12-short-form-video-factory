# TASK — ledger isolation by workflow_id (H22) + non-string meter fails closed (H60)

## Why
**H22:** `run_id` (`app/core/ids.py`) is only unique *within one workflow's* runs dir, so two
DIFFERENT workflows started in the same UTC second share a `run_id`. The budget ledger is
machine-wide and keys per-run accounting (`_run_sum`) and `read_run_spend` by `run_id`+`meter`
only, so those two runs' spend MERGES — over-counting each other's per-run ceiling and
cross-reporting spend. Fix: namespace ledger per-run accounting by `workflow_id` too (write it on
every entry; filter by it). Do NOT change `run_id` generation or the run-dir layout — the fix is in
the ledger, invisible to the product.

**H60:** a valid-JSON `reserved`/`actual` line whose `meter` is present but not a usable string
currently passes through `_as_str` → `""` and silently drops out of `_run_sum`/`_day_sum` (spend
under-count). The engine always writes a string meter, so a non-string meter is corruption and must
fail closed as `BudgetError`, uniform with the missing-token (H59) and bad-amount (H23) checks.

`workflow_id` is a NEW ledger field: read it TOLERANTLY (absent → `""`), because durable pre-H22
ledgers have no such field and must keep working (a legacy line totals in the `""` namespace). It is
a keyword-only param defaulting to `""` on the public methods, so existing callers/tests are
unaffected; the production call sites pass the real `workflow_id`.

Frozen RED tests (committed, do not modify):
- `tests/sdk/test_budget.py`: `test_run_total_isolates_two_workflows_sharing_a_run_id`,
  `test_read_run_spend_isolates_two_workflows_sharing_a_run_id`,
  `test_reconcile_preserves_workflow_id_isolation`,
  `test_legacy_ledger_line_without_workflow_id_totals_in_the_default_namespace`,
  `test_a_non_string_meter_on_a_spend_line_fails_closed` (parametrized reserved/actual × 4 bad meters).
- `tests/core/test_preflight.py`: `test_per_run_headroom_isolates_a_sibling_workflow_sharing_the_run_id`.

## Changes

### 1. `sdk/sfvf/_budget.py`

**(a) `_TokenState`** — add a field:
```python
@dataclass
class _TokenState:
    reserved_amount: float | None = None
    actual_amount: float | None = None
    meter: str = ""
    run_id: str = ""
    workflow_id: str = ""
    day: date | None = None
```

**(b) `_token_states`** — validate meter (H60) and read workflow_id (H22). Replace the
`reserved`/`actual` handling so BOTH validate the meter and capture `workflow_id`:
```python
        state = states.setdefault(token, _TokenState())
        if kind in ("reserved", "actual"):
            meter = entry.get("meter")
            if not isinstance(meter, str) or not meter:
                raise BudgetError("budget ledger spend entry has an invalid meter")
            run_id = _as_str(entry.get("run_id"))
            workflow_id = _as_str(entry.get("workflow_id"))
        if kind == "reserved":
            state.reserved_amount = _require_amount(entry.get("amount"))
            state.meter = meter
            state.run_id = run_id
            state.workflow_id = workflow_id
            state.day = _ts_date(entry.get("ts"))
        elif kind == "actual":
            state.actual_amount = _require_amount(entry.get("amount"))
            if not state.meter:
                state.meter = meter
            if not state.run_id:
                state.run_id = run_id
            if not state.workflow_id:
                state.workflow_id = workflow_id
```
(The missing-token guard above this block is UNCHANGED. `workflow_id` uses `_as_str` — tolerant,
absent → `""` — so legacy lines do not fail closed. `meter` is now required-valid on spend lines.)

**(c) `_run_sum`** — add the workflow_id filter:
```python
def _run_sum(
    states: Mapping[str, _TokenState], run_id: str, meter: str, workflow_id: str = ""
) -> float:
    return sum(
        (
            state.effective_amount()
            for state in states.values()
            if state.run_id == run_id
            and state.meter == meter
            and state.workflow_id == workflow_id
        ),
        start=0.0,
    )
```

**(d) `read_run_spend`** — add the workflow_id filter (mirrors `_run_sum`):
```python
def read_run_spend(ledger_path: Path, run_id: str, *, workflow_id: str = "") -> dict[str, float]:
    try:
        entries = _read_ledger(ledger_path)
        spend: dict[str, float] = {}
        for state in _token_states(entries).values():
            if state.run_id == run_id and state.workflow_id == workflow_id and state.meter:
                spend[state.meter] = spend.get(state.meter, 0.0) + state.effective_amount()
        return spend
    except (BudgetError, ValueError, OSError, OverflowError):
        return {}
```
(Keep the best-effort try/except EXACTLY as-is — a corrupt ledger still returns `{}`.)

**(e) `_record`** — add `workflow_id` param and write it:
```python
    def _record(
        self,
        *,
        token: str,
        run_id: str,
        workflow_id: str,
        meter: str,
        unit: str,
        amount: float,
        kind: str,
        note: str,
    ) -> dict[str, str | float]:
        return {
            "ts": _format_ts(self._now()),
            "token": token,
            "run_id": run_id,
            "workflow_id": workflow_id,
            "meter": meter,
            "unit": unit,
            "amount": amount,
            "kind": kind,
            "note": note,
        }
```

**(f) `reserve`** — add `workflow_id` (keyword-only, default `""`); thread to `_run_sum` and
`_record`:
```python
    def reserve(
        self,
        *,
        run_id: str,
        meter: str,
        unit: str,
        estimate: float,
        note: str = "",
        workflow_id: str = "",
    ) -> str:
        with self._held():
            ...  # kill-switch + _require_amount + _snapshot UNCHANGED
            projected_run = _run_sum(states, run_id, meter, workflow_id) + amount
            ...  # ceiling checks UNCHANGED
            _append_line(
                self._ledger_path,
                self._record(
                    token=token,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    meter=meter,
                    unit=unit,
                    amount=amount,
                    kind="reserved",
                    note=note,
                ),
            )
            return token
```
(The per-DAY ceiling / `_day_sum` path is UNCHANGED — a per-day cap is a global machine-wide cap,
not workflow-scoped.)

**(g) `reconcile`** — recover `workflow_id` from the reserved line (alongside run_id/meter/unit) and
write it on the actual. Keep the `self._snapshot()` fail-closed call added in the prior increment:
```python
    def reconcile(self, token: str, *, actual: float, note: str = "") -> None:
        with self._held():
            amount = _require_amount(actual)
            self._snapshot()  # fail closed on a corrupt ledger before appending (H23)
            run_id = ""
            workflow_id = ""
            meter = ""
            unit = ""
            for entry in _read_ledger(self._ledger_path):
                if entry.get("kind") == "reserved" and entry.get("token") == token:
                    run_id = _as_str(entry.get("run_id"))
                    workflow_id = _as_str(entry.get("workflow_id"))
                    meter = _as_str(entry.get("meter"))
                    unit = _as_str(entry.get("unit"))
                    break
            _append_line(
                self._ledger_path,
                self._record(
                    token=token,
                    run_id=run_id,
                    workflow_id=workflow_id,
                    meter=meter,
                    unit=unit,
                    amount=amount,
                    kind="actual",
                    note=note,
                ),
            )
```

**(h) `run_total`** — add `workflow_id` (keyword-only, default `""`); thread to `_run_sum`:
```python
    def run_total(self, run_id: str, meter: str, *, workflow_id: str = "") -> float:
        with self._held():
            return _run_sum(self._snapshot(), run_id, meter, workflow_id)
```

### 2. `app/core/preflight.py` — `check_atomic_budget`
Add a keyword-only `workflow_id: str = ""` param (after `run_id`) and thread it to `run_total`:
```python
def check_atomic_budget(
    estimate: Estimate,
    safety_factor: float,
    budget: BudgetConfig,
    run_id: str,
    *,
    workflow_id: str = "",
) -> str | None:
    ...
            run_used = guard.run_total(run_id, meter, workflow_id=workflow_id)
            day_used = guard.day_total(meter)
    ...
```
(`day_total` is UNCHANGED — global per-day cap.)

### 3. `app/core/supervisor.py`
- The `check_atomic_budget(...)` call (~line 478): pass `workflow_id=wiring.workflow_id`.
- The `read_run_spend(...)` call (~line 317): pass `workflow_id=wiring.workflow_id`.

### 4. `sdk/sfvf/context.py`
The `guard.reserve(run_id=self.run_id, ...)` call (~line 570): add `workflow_id=self.workflow_id`.

### 5. `app/learning/completion.py` + `app/api/learning.py`
- `make_openrouter_completion(...)` (`completion.py`): add a `workflow_id: str` parameter (place it
  next to `run_id`), and pass `workflow_id=workflow_id` to `guard.reserve(...)`.
- The `make_openrouter_completion(...)` call in `app/api/learning.py` (~line 58, inside the
  `factory(workflow_id, run_id)` closure): pass `workflow_id=workflow_id`.

## Scope / do NOT
- Do NOT change `app/core/ids.py`, `run_id` generation, or run-dir layout.
- Do NOT change `day_total` / `_day_sum` (per-day cap stays global).
- Do NOT modify any test, or `docs/HARDENING.md` (the supervisor updates the ledger doc separately).
- No new dependencies. `workflow_id` stays a plain `str`.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/sdk/test_budget.py tests/core/test_preflight.py tests/integration/test_budget_gate.py tests/sdk/test_budget_report.py tests/integration/test_budget_release.py tests/integration/test_agents_budget_release.py -q` → all pass (the new H22/H60 tests plus every prior budget/preflight/report/release test — existing calls that omit `workflow_id` must still work via the `""` default).
- `ruff check sdk app tests` and `ruff format --check sdk app tests` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
