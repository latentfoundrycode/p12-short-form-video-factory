# TASK T2b-2c — Budget denial → `stopped-budget`, and surface run spend in `RequestRecord.budget`

## Goal (one sentence)
Wire the already-existing `stopped-budget` request status and `RequestRecord.budget` field so a run
that the budget guard refused ends **`stopped-budget`** (not generic `failed`), and every run under a
configured budget records **what it spent** — implementing exactly the frozen contract tests, and
touching nothing else.

## What already exists (do NOT re-add)
- `RequestStatus` already includes `"stopped-budget"`; `RequestRecord.budget: dict | None` already
  exists and is already in `REQUEST_OPTIONAL_FIELDS` (`app/core/records.py`). The schema is done —
  only the **wiring that populates them** is missing.
- The SDK gate (`Context._budget_reserve/_reconcile`, T2b-1) already raises `sfvf._budget.BudgetError`
  subclasses (`BudgetExceededError`, `KillSwitchEngagedError`) before any HTTP when a ceiling or the
  kill-switch blocks a paid call, and writes a JSONL ledger keyed by `run_id` (the run-folder name).
- `sfvf._budget` already has `_read_ledger`, `_token_states`, and `_TokenState.effective_amount()`
  (reconciled actual if present, else reserved). Reuse them; do not duplicate ledger parsing.
- `sfvf.runner.main()` already catches any entry failure, emits one
  `{"t":"log","level":"error","msg":...,"trace":...}` event, and returns exit code 1.

## The frozen contract (already committed — do not edit these files)
- `tests/sdk/test_budget_report.py` — `read_run_spend`
- `tests/sdk/test_runner_budget.py` — runner budget signal
- `tests/integration/test_budget_status.py` — `_aggregate_status` precedence + full path + surfacing
- `tests/core/test_records.py` (the two new `..._budget...` tests) — `update_request(budget=...)`
- `tests/stubs/budget_denied/`, `tests/stubs/budget_spender/` — stub workflows the integration uses

Make all of them pass **without modifying any test**. They are the exact spec; where this brief and a
test disagree, the test wins.

## Changes to make

### 1. `sdk/sfvf/_budget.py` — add a best-effort reporting read
Add a module-level function:

```
def read_run_spend(ledger_path: Path, run_id: str) -> dict[str, float]
```

- Returns the per-meter **effective** amount (reconciled actual if present, else the open reserved
  estimate — never both) summed over ledger entries whose `run_id` equals the argument. Reuse
  `_read_ledger` + `_token_states`; sum `state.effective_amount()` per `state.meter` where
  `state.run_id == run_id` and `state.meter` is non-empty.
- **Best-effort, NOT a gate.** A missing ledger yields `{}` (already how `_read_ledger` behaves on a
  missing file). A **corrupt** ledger must yield `{}` too — catch `BudgetError` from `_read_ledger`
  and return `{}`. This deliberately diverges from the gate's fail-closed read: this runs at finalize
  on an already-finished run, so it must never turn a completed run into a recording failure. Put a
  one-line comment saying so.

### 2. `sdk/sfvf/runner.py` — signal a budget denial distinctly
- Add `from ._budget import BudgetError` (top-level; `_budget` is stdlib-only, no heavy deps).
- Add a module constant `EXIT_BUDGET_DENIED = 2` (0 = success, 1 = generic failure, 2 = budget).
- Add a small helper that walks the raised exception's cause/context chain and returns `"budget"` if
  any link is a `BudgetError`, else `None`. Walk `exc` then `exc.__cause__ or exc.__context__`,
  guarding against cycles (track seen ids). This matters because `_run` wraps the entry error as
  `_EntryFailedError(...) from exc`, and a workflow may itself catch-and-re-raise, so the `BudgetError`
  can be one or two links down the chain.
- In `main()`'s `except Exception as exc:` block: after building the event (keep the existing
  `msg`/`trace`), compute the reason; if it is `"budget"`, add `event["reason"] = "budget"` and
  `return EXIT_BUDGET_DENIED`; otherwise behave exactly as today (`return 1`, no `reason` key).

### 3. `app/core/records.py` — let `update_request` carry the budget block
- Add a keyword-only `budget: dict[str, Any] | None = None` param to `update_request`.
- In the `model_copy(update=...)`, set `"budget": current.budget if budget is None else budget` so a
  `None` argument preserves the current value (which stays omitted from JSON via `_dump_owned`) and a
  dict overwrites it. No other change; `write_json_atomic(..., _dump_owned(updated, REQUEST_OPTIONAL_FIELDS))`
  already drops it when `None`.

### 4. `app/core/supervisor.py` — map the denial and surface spend
- Import the new seams: `from sfvf.runner import EXIT_BUDGET_DENIED` and
  `from sfvf._budget import read_run_spend`.
- `_RunState`: add `budget_denied: bool = False` and two lock-guarded methods, mirroring
  `was_stopped()`: `mark_budget_denied()` (sets it True) and `was_budget_denied()` (reads it).
- `_RunState.finish_request`: add a keyword-only `budget: dict[str, Any] | None = None` param and
  pass it straight through to `update_request(...)`.
- Add a helper:
  ```
  def _budget_report(wiring: _ContextWiring) -> dict[str, Any] | None:
  ```
  Return `None` when `wiring.budget is None`; otherwise return
  `{"spend": read_run_spend(wiring.budget.ledger_path, wiring.run_id),
    "per_run": dict(wiring.budget.per_run), "per_day": dict(wiring.budget.per_day)}`.
- `_aggregate_status`: add a keyword-only `budget_denied: bool = False` param. Precedence:
  a user `stopped` still returns `"stopped"` FIRST (unchanged); then, if `budget_denied`, return
  `"stopped-budget"` (before the pending/running guard and before the complete/failed/partial logic).
  Everything else is unchanged.
- `_run_one_video`: after `returncode = proc.wait()`, treat `returncode == EXIT_BUDGET_DENIED` as a
  budget denial: call `state.mark_budget_denied()` and make the video `status` be `"stopped"` for
  that case as well (i.e. `"stopped"` when `state.was_stopped()` OR the return code is
  `EXIT_BUDGET_DENIED`, else the existing complete/failed choice). The `except Exception` fallback
  branch is unchanged.
- `_run_prepare`: capture the return code; if it equals `EXIT_BUDGET_DENIED`, call
  `state.mark_budget_denied()` before the existing `!= 0` failure return. (Research runs in prepare,
  so a denial can happen there.)
- `run_request`: in the `if not ok:` prepare-failure branch, when it is NOT a user stop, choose the
  status as `"stopped-budget" if state.was_budget_denied() else "failed"`.
- Pass `budget=_budget_report(wiring)` to **every** `state.finish_request(...)` call (the `_run_videos`
  return, and each prepare-branch return in `run_request`) so a configured run always records its
  spend regardless of terminal status. `_run_videos` also passes
  `budget_denied=state.was_budget_denied()` into its `_aggregate_status(...)` call.

## Constraints / do-nots
- Do **not** modify any file under `tests/`. Do **not** touch the frozen T2a/T2b-1/T2b-2a contracts
  (`sdk/sfvf/context.py` budget code, `app/core/budget_config.py`) — this increment is downstream of
  them and changes none of their behavior. `test_no_budget_config_is_passthrough` and the
  secret-injection/redaction suites must stay green: a run with `budget=None` behaves exactly as
  before (no ledger read, no budget block).
- No new dependencies. No network, no real spend, no live keys.
- `read_run_spend` and `_budget_report` are best-effort at finalize — they must never raise into the
  record-write path.
- Match surrounding style (type hints, keyword-only params, comment density). Keep `mypy --strict`
  and `ruff` clean.

## Verify before you hand back
Run from the worktree root with `./.venv/Scripts/python.exe`:
- `-m pytest tests/sdk/test_budget_report.py tests/sdk/test_runner_budget.py tests/integration/test_budget_status.py tests/core/test_records.py tests/integration/test_budget_gate.py tests/api/test_budget_activation.py tests/core/test_supervisor.py -q` → all pass (the last three prove no regression to the existing budget/supervisor behavior).
- `-m ruff check .` and `-m ruff format --check .` → clean.
- `-m mypy sdk app` (per `mypy.ini`) → clean.
