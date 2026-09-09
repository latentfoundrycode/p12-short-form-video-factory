# TASK C-4 — atomic pre-flight budget check (§5.4b, attended core)

## Goal (one sentence)
An atomic workflow refuses to START when its estimated cost (× `safety_factor`) cannot fit the budget
headroom — so it never strands spend on a half-finished all-or-nothing run.

## Frozen contract (already committed — do not edit any test)
- `tests/core/test_preflight.py`: `check_atomic_budget(estimate, safety_factor, budget, run_id)` unit
  behaviour + an integration where an atomic workflow with unaffordable history refuses to start.
- `tests/core/test_estimate.py`: only completed history (`complete`/`partial`) feeds estimates — a
  still-`running` run is excluded; `partial` is included.
The `check_atomic_budget` signature and the `Estimate` type are frozen — do not change them.

## Changes

### 1. `app/core/estimate.py` — count only completed runs
Replace the `EXCLUDED_STATUSES` denylist with an **allowlist** of completed statuses so running/pending
(and the current run at admission) are not counted:
- Define `INCLUDED_STATUSES = frozenset({"complete", "partial"})` (you may drop `EXCLUDED_STATUSES`).
- In `_candidates`, keep a run only when `record.status in INCLUDED_STATUSES and not record.dry_run`.
This still excludes failed/stopped/stopped-budget and dry; it additionally excludes running/pending.

### 2. `app/core/preflight.py` — implement `check_atomic_budget`
Fill the body per its docstring:
- Build a read-only `BudgetGuard(budget.ledger_path, ceilings=Ceilings(per_run=budget.per_run,
  per_day=budget.per_day), kill_switch_path=budget.kill_switch_path)` (default clock).
- For each `meter, amount` in `estimate.per_meter`: `need = amount * safety_factor`.
  - If `meter in budget.per_run` and `need > budget.per_run[meter] - guard.run_total(run_id, meter)` →
    return a message naming the meter (e.g. `f"estimated {meter} cost {need:g} exceeds per-run budget"`).
  - Else if `meter in budget.per_day` and `need > budget.per_day[meter] - guard.day_total(meter)` →
    return a message naming the meter (per-day).
  - A meter absent from a ceiling map is unlimited (skip that ceiling).
- If every meter fits (or `per_meter` is empty) return `None`. Read-only; do not reserve anything.

### 3. `app/core/supervisor.py` — refuse an unaffordable atomic run before it starts
In `run_request`, immediately AFTER the `create_request(...)` call and BEFORE `if workflow.prepare:`,
add (only when `workflow.atomic and wiring.budget is not None`):
- `affects = frozenset(p.key for p in manifest.params if p.affects_cost)`
- `est = estimate_cost(run_dir.parent.parent, workflow_id, params, affects)` (the runs base is the
  grandparent of this run's dir; import `estimate_cost` from `app.core.estimate`).
- `factor = workflow.safety_factor if workflow.safety_factor is not None else 1.0`
- `refusal = check_atomic_budget(est, factor, wiring.budget, run_id)` (import from `app.core.preflight`).
- If `refusal is not None`: record a log event explaining it via
  `state.record_event(run_dir, {"t": "log", "level": "error", "msg": f"atomic pre-flight refused: {refusal}"}, "prep")`,
  then `state.mark_pending_stopped(run_dir, atomic=workflow.atomic)` and
  `return state.finish_request(run_dir, atomic=workflow.atomic, status="stopped-budget",
  ended_utc=format_utc_z(utc_now()), budget=_budget_report(wiring))`. Do not run prepare or videos.

## Constraints / do-nots
- Do NOT edit any test. Do NOT change the budget ledger/gate mechanics, C-1 cost, or C-2 forecast. The
  pre-flight is read-only (a check) — the whole-run reservation, mid-run forecast re-check, and
  scheduled-run skip/stop are later increments; do not add them here.
- Keep `ruff` and `mypy --strict` clean; match surrounding style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_preflight.py tests/core/test_estimate.py tests/core/test_supervisor.py tests/api/test_budget_activation.py -q` → all pass.
- `-m ruff check .` and `-m mypy sdk app` → clean.
