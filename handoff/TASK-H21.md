# TASK H21 — Refuse a real paid call when no budget is configured (fail-closed-when-unset)

## Goal (one sentence)
Flip the SDK budget gate so a real (non-dry) paid provider call with **no budget configured** is
REFUSED before any spend, instead of the current silent passthrough — closing the fail-open-when-unset
gap (docs/HARDENING.md H21).

## Background (already true — do not change)
- The gate lives in `sdk/sfvf/context.py`: `Context._budget_reserve(meter, unit)` is called by the two
  paid providers (`agents._post_chat_completion` for OpenRouter, `media.video.generate` for Higgsfield)
  right before the real HTTP call. It is reached ONLY on the non-dry path (both providers early-return on
  `ctx.dry_run` before reserving) and only AFTER the provider key is read (`ctx.secret(...)`).
- Today `_budget_reserve` returns `None` when `self._file.budget is None` (passthrough — the fail-open
  bug). When a budget IS configured it reserves via `BudgetGuard` and returns a token; a
  configured-but-missing-estimate already raises `BudgetError` (fail-closed).
- With T2b-2c merged, a `BudgetError` raised here propagates out of the workflow, the runner exits
  `EXIT_BUDGET_DENIED`, and the supervisor labels the run `stopped-budget` — so refusing here yields a
  clean, correctly-labelled stop with no spend.

## The frozen contract (already committed — do not edit any test)
- `tests/integration/test_budget_gate.py::test_no_budget_config_refuses_the_paid_call` — a non-dry
  `agents.llm` with `budget=None` must raise `BudgetError` and make NO HTTP call, writing no ledger.
  (This replaces the old `test_no_budget_config_is_passthrough`.) Currently RED.
- The three real-adapter integration suites (`test_agents_openrouter_llm.py`,
  `test_agents_openrouter_research.py`, `test_video_higgsfield.py`) now carry a permissive budget in
  their `_ctx` helper; they must stay GREEN (the real path is gated-and-allowed).

## Change to make — ONLY `sdk/sfvf/context.py`
In `Context._budget_reserve`, replace the `cfg is None` passthrough with a fail-closed refusal:

- When `self._file.budget is None`, **raise** `BudgetError` with a clear, key-free message, e.g.
  `raise BudgetError(f"no budget configured; refusing paid call for meter {meter!r} — set SFVF_BUDGET_CONFIG")`
  instead of `return None`.
- Update the return type annotation to `str` (it now always returns a token string or raises).
- Update the method docstring: no-config is now fail-closed (refuse the paid call), not passthrough.
- Leave `_budget_reconcile` as-is (its `token is None`/`cfg is None` guards stay valid and harmless).
- Do not touch `agents.py` / `media/video.py` — they already propagate whatever `_budget_reserve`
  raises, which is the intended abort.

## Constraints / do-nots
- Do NOT modify any test. Do NOT change the dry_run stubs, the secret path, or the T2a engine.
- `dry_run` must be entirely unaffected (it never reaches `_budget_reserve`).
- A configured budget must behave exactly as before (reserve/deny/reconcile unchanged).
- Keep `mypy --strict` and `ruff` clean; match surrounding style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_budget_gate.py tests/integration/test_agents_openrouter_llm.py tests/integration/test_agents_openrouter_research.py tests/integration/test_video_higgsfield.py tests/sdk/test_agents.py tests/sdk/test_budget.py tests/integration/test_budget_status.py -q` → all pass (the reversed contract goes green; the migrated adapters + the untouched dry_run/no-key tests stay green).
- `-m ruff check .` and `-m mypy sdk app` → clean.
