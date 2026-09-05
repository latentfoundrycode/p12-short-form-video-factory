# TASK T2b-1 — gate the paid-call paths with the budget guard (SDK side)

**Builder:** Cursor. **Product code only** in `sdk/sfvf/context.py`, `sdk/sfvf/agents.py`, and
`sdk/sfvf/media/video.py`. Do NOT touch `tests/`, `docs/`, `handoff/`, or `sdk/sfvf/_budget.py` (T2a is
frozen). The reviewer contract `tests/integration/test_budget_gate.py` is FROZEN.

Wire the T2a `sfvf._budget.BudgetGuard` into the two paid providers so a run cannot spend past its
ceilings or an engaged kill-switch. No live call is made or enabled — HTTP is mocked in the contract.

## 1. `sdk/sfvf/context.py`

`BudgetConfig` and `ContextFile.budget` are already defined (scaffolding). Implement the two stubbed
`Context` methods (currently `raise NotImplementedError`):

```python
def _budget_reserve(self, meter: str, unit: str) -> str | None:
    cfg = self._file.budget
    if cfg is None:
        return None
    estimate = cfg.estimates.get(meter)
    if estimate is None or not (estimate > 0):
        # Configured budget but no positive estimate for this meter → fail closed (never reserve 0
        # as "unknown"): reserving nothing would let the call through ungated.
        raise BudgetError(f"no positive budget estimate configured for meter {meter!r}")
    guard = self._budget_guard(cfg)
    return guard.reserve(run_id=self.run_id, meter=meter, unit=unit, estimate=estimate)

def _budget_reconcile(self, token: str | None, *, actual: float) -> None:
    cfg = self._file.budget
    if token is None or cfg is None:
        return
    self._budget_guard(cfg).reconcile(token, actual=actual)
```

Add a small private helper that builds a guard from the config (a fresh guard per call is fine — the
engine is stateless over the ledger file):

```python
def _budget_guard(self, cfg: BudgetConfig) -> BudgetGuard:
    return BudgetGuard(
        cfg.ledger_path,
        ceilings=Ceilings(per_run=cfg.per_run, per_day=cfg.per_day),
        kill_switch_path=cfg.kill_switch_path,
    )
```

Import at top: `from ._budget import BudgetError, BudgetGuard, Ceilings`. (`_budget_reserve` may raise
`BudgetError`/`BudgetExceededError`/`KillSwitchEngagedError` — let them propagate.)

## 2. `sdk/sfvf/agents.py` — OpenRouter (meter "openrouter", unit "usd")

In `_post_chat_completion(ctx, body)` (the shared path for `llm` and `research`), reserve BEFORE the
request loop and reconcile AFTER a successful 200 with the real cost:

```python
def _post_chat_completion(ctx: Context, body: dict[str, Any]) -> dict[str, Any]:
    key = ctx.secret("OPENROUTER_API_KEY")
    token = ctx._budget_reserve("openrouter", "usd")   # raises → no HTTP happens
    with _http_client() as client:
        ... existing retry loop, returns data on 200 ...
    cost = data.get("usage", {}).get("cost")
    if cost is not None:
        ctx._budget_reconcile(token, actual=float(cost))
    return data
```

Reserve must happen before opening the client / making any request (so a refusal makes NO network
call). Reconcile only on a successful call when `usage.cost` is present; if it is absent, leave the
reservation standing (the estimate holds — conservative). Do not swallow a reserve exception.

## 3. `sdk/sfvf/media/video.py` — Higgsfield (meter "higgsfield", unit "credits")

In `generate(...)`, after the `dry_run` early return and after the NotImplementedError guards, reserve
BEFORE the submit request (before building the client / calling the API), so a refused reservation
makes no HTTP call:

```python
    key = ctx.secret("HIGGSFIELD_API_KEY")
    token = ctx._budget_reserve("higgsfield", "credits")   # raises → no submit
    ... existing submit/poll/download ...
```

Higgsfield returns no per-request cost here, so leave the reservation standing at the estimate (do not
reconcile in this increment). Keep everything else identical.

## Rules

Never log a secret. mypy-strict clean. No new dependency. Touch ONLY the three files named. Do not alter
`_budget.py` or any test.

## Acceptance

`tests/integration/test_budget_gate.py` passes (6 tests): an LLM call is blocked (no HTTP) when the
estimate exceeds the ceiling; an allowed LLM call reserves then reconciles the real `usage.cost` into the
ledger; the kill-switch blocks the LLM call; no budget config is passthrough (no ledger written); a
configured budget missing the meter's estimate fails closed; a Higgsfield call is blocked when its
estimate exceeds the ceiling. The existing OpenRouter/Higgsfield integration tests and the rest of the
suite still pass.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_budget_gate.py tests/integration/test_agents_openrouter_llm.py tests/integration/test_agents_openrouter_research.py tests/integration/test_video_higgsfield.py
```
(The full `pytest` run may show pre-existing `finalize`/`example_workflow` HyperFrames failures not
installed in this worktree; CI runs them green. Ignore those.)
