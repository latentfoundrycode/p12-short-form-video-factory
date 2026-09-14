# TASK G-7b — real OpenRouter learning completion (over mocked HTTP) (§5.11)

## Goal (one sentence)
Add `app/learning/completion.py` with `make_openrouter_completion(...)`, which returns the real
`complete: CompleteFn` seam that G-7a's `make_optimizer` needs: it reserves a SEPARATE `learning`
budget meter, POSTs to OpenRouter `/chat/completions`, returns the assistant content, and reconciles
the actual `usage.cost`. Tests drive it through an injected `client_factory` (an `httpx2.MockTransport`)
— NO network call, NO spend. The first real run is an attended money-gate handled elsewhere.

## Governing spec (verbatim — Architecture §5.11 + PRD budget separation)
> run the SkillOpt-derived optimiser to propose bounded edits.

The learning budget is SEPARATE from the generation budget (PRD: improving a workflow must never eat
the video budget). We realise that as a distinct budget **meter** named `learning`, gated by the same
`BudgetGuard` money-engine used for generation — never the `openrouter` meter.

## Frozen contract (already committed — do NOT edit)
`tests/integration/test_learning_completion.py`.

## Reference implementation to MIRROR (do not modify it)
`sdk/sfvf/agents.py` — `_post_chat_completion` (auth header, POST `/chat/completions`, 402/non-200
handling) and `_usage_cost` (safe parse of `usage.cost`: a bool/non-number/NaN/Inf/negative → treat as
absent). Study `Context._budget_reserve` / `_budget_reconcile` in `sdk/sfvf/context.py` for the
fail-closed reservation discipline. Mirror these; do not import the private helpers.

## What to implement — `app/learning/completion.py` (new)
Imports: `httpx2` the SAME way `agents.py` does (guard the type import under `TYPE_CHECKING`, do the
real `import httpx2` inside the client-building path), plus `from sfvf._budget import BudgetError,
BudgetGuard, Ceilings` and `from sfvf.context import BudgetConfig`. Reuse `CompleteFn` from
`app.learning.optimizer` (import it; do not redefine).

Define:
- `LEARNING_METER = "learning"` (module constant).
- `class CompletionError(Exception)` — a non-budget failure (missing key, non-200, missing content).
- `def _default_client_factory() -> httpx2.Client` — builds `httpx2.Client(base_url=
  "https://openrouter.ai/api/v1", timeout=...)` (mirror `agents._http_client`'s base_url/timeout).
- `def make_openrouter_completion(*, secrets: Mapping[str, str], budget: BudgetConfig | None,
  model: str, run_id: str, client_factory: Callable[[], httpx2.Client] = _default_client_factory)
  -> CompleteFn`

The returned `complete(messages: list[dict[str, str]]) -> str` does, IN THIS ORDER:
1. **Validate the key first.** `key = secrets.get("OPENROUTER_API_KEY")`; if falsy → raise
   `CompletionError` (no reservation, no client). (The key is never logged or put in an error message.)
2. **Reserve the learning meter (fail-closed).** If `budget is None` → raise `BudgetError`
   (fail-closed; refuse the paid call). Else read `estimate = budget.estimates.get(LEARNING_METER)`;
   if `estimate is None or not (estimate > 0)` → raise `BudgetError`. Build a guard
   `BudgetGuard(budget.ledger_path, ceilings=Ceilings(per_run=budget.per_run, per_day=budget.per_day),
   kill_switch_path=budget.kill_switch_path)` and `token = guard.reserve(run_id=run_id,
   meter=LEARNING_METER, unit="usd", estimate=estimate)`. A kill-switch or ceiling refusal raises a
   `BudgetError` subclass — let it propagate. **Do all this before building any HTTP client**, so a
   fail-closed path makes no network call (the contract asserts `client_factory` was never invoked).
3. **POST.** `with client_factory() as client:` → `resp = client.post("/chat/completions",
   headers={"Authorization": f"Bearer {key}"}, json={"model": model, "messages": messages})`.
   On `resp.status_code != 200` → raise `CompletionError(f"OpenRouter error {resp.status_code}")`
   (do NOT include the body/key). (Single attempt — no 429 retry in this increment; see note.)
4. **Meter + return.** Parse `data = resp.json()`. Compute `cost` with a local `_usage_cost` mirroring
   `agents._usage_cost`; if `cost is not None` → `guard.reconcile(token, actual=cost)` (mirror
   agents: when cost is absent the reservation stands at the estimate — do NOT reconcile). Extract
   `content = data["choices"][0]["message"]["content"]`; if it is missing or not a `str` → raise
   `CompletionError`. Return `content`.

## Constraints / do-nots
- Touch ONLY `app/learning/completion.py` (new). Do NOT edit the test, `agents.py`, `optimizer.py`,
  `engine.py`, or anything else. No real network in the module's own tests (the contract injects a
  mock transport). No new dependency.
- The bearer key must never appear in a log line or an exception message.
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Note for the supervisor (do not implement here)
No 429/Retry-After retry or shared rate-limiter in this increment (agents.llm has both). A learning
run is user-initiated and infrequent; a 429 surfaces as `CompletionError` to retry. Retry/limiter
parity is a tracked hardening follow-up.

## Scope
- `app/learning/completion.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_learning_completion.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
