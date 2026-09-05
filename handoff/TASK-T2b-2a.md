# TASK T2b-2a — activate the budget gate (load config + inject into context.json)

**Builder:** Cursor. **Product code only** in these four files:
`app/core/budget_config.py`, `app/main.py`, `app/api/runs.py`, `app/core/supervisor.py`.
Do NOT touch `tests/`, `docs/`, `handoff/`, `budget.toml`, `sdk/`. The reviewer contract
`tests/api/test_budget_activation.py` is FROZEN.

The T2b-1 SDK gate (`Context._budget_reserve/_reconcile`) is inert until it receives a `BudgetConfig` in
`context.json`. This increment loads a TOML budget file and threads it through so every run's context.json
carries the budget block. Env-gated exactly like the secret store. No live call is made or enabled.

## 1. `app/core/budget_config.py` — implement `load_budget_config`

The skeleton defines `BudgetConfigError` and the frozen signature `load_budget_config() -> BudgetConfig |
None`. Implement:
- If `os.environ.get("SFVF_BUDGET_CONFIG")` is unset/empty → return `None`.
- Otherwise read that path. If the file is missing or unreadable, or the TOML is malformed, raise
  `BudgetConfigError` (fail closed — never return None on a configured-but-broken file). Use `tomllib`
  (stdlib) with `open(path, "rb")`; wrap `FileNotFoundError`/`OSError`/`tomllib.TOMLDecodeError` in
  `BudgetConfigError`.
- Parse per-provider tables into the three per-meter maps. The TOML shape is:
  ```toml
  [openrouter]
  per_run = 0.50
  per_day = 2.00
  estimate = 0.05
  ```
  → `per_run={"openrouter":0.50,...}`, `per_day={"openrouter":2.00,...}`,
  `estimates={"openrouter":0.05,...}`. A meter may omit any of the three keys (then it is simply absent
  from that map). Coerce numbers to `float`.
- Derive the paths from the state dir: `state = Path(os.environ.get("SFVF_BUDGET_STATE") or <default>)`
  where the default is `APP_ROOT / "state" / "budget"` (import `APP_ROOT` from `app.paths`). Set
  `ledger_path = (state / "ledger.jsonl").resolve()` and `kill_switch_path = (state / "STOP").resolve()`.
  (The tests assert both are absolute and live under the configured state dir.)
- Return `BudgetConfig(ledger_path=..., kill_switch_path=..., per_run=..., per_day=..., estimates=...)`
  (import `BudgetConfig` from `sfvf.context`).

## 2. `app/main.py` — `create_app`

Add a keyword-only param `budget: BudgetConfig | None = None` (import `BudgetConfig` from `sfvf.context`).
Set `application.state.budget = budget if budget is not None else load_budget_config()` (import
`load_budget_config` from `app.core.budget_config`). So an explicit arg wins; otherwise it loads from the
env (returning None when unset).

## 3. `app/api/runs.py`

Add a `_budget(request)` accessor mirroring `_secrets`:
```python
def _budget(request: Request) -> BudgetConfig | None:
    return getattr(request.app.state, "budget", None)
```
Add a keyword-only `budget: BudgetConfig | None = None` param to `admit_run`, pass it into the
`run_request(...)` call inside `target()` (add `budget=budget`), and at the `admit_run(...)` call site (the
run-creation endpoint, near the existing `secrets=_secrets(request)`) pass `budget=_budget(request)`.

## 4. `app/core/supervisor.py`

- Add `budget: BudgetConfig | None = None` field to the `_ContextWiring` dataclass (import `BudgetConfig`
  from `sfvf.context`).
- Add a keyword-only `budget: BudgetConfig | None = None` param to `run_request`, and set
  `budget=budget` when constructing the `_ContextWiring(...)`.
- In `_make_context`, pass `budget=wiring.budget` into the `ContextFile(...)` constructor.

That is the whole path: config file → `create_app` → `_budget` → `admit_run` → `run_request` → wiring →
`_make_context` → `context.json`. The SDK (T2b-1) already reads `ContextFile.budget` and enforces it.

## Rules

Never log a secret. mypy-strict clean. No new dependency (tomllib is stdlib). Touch only the four files
named. Do not change `sdk/` or any test/doc.

## Acceptance

`tests/api/test_budget_activation.py` passes (8 tests): loader returns None with no env; parses ceilings/
estimates and derives absolute ledger+kill-switch paths under the state dir; fails closed
(`BudgetConfigError`) on a missing or malformed configured file; `create_app` loads from env (and is None
without it); a run's context.json carries the budget block at spawn; and no config leaves it absent. The
existing suite (secret injection/exposure/redaction, supervisor, runs) still passes.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_budget_activation.py tests/api/test_secret_injection.py tests/core/test_supervisor.py tests/api/test_runs.py
```
(The full `pytest` run may show pre-existing `finalize`/`example_workflow` HyperFrames failures not
installed in this worktree; CI runs them green. Ignore those.)
