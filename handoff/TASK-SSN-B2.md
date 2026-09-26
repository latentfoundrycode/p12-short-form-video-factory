# TASK-SSN-B2 — Per-video cross-meter budget ceiling

Add a per-video AGGREGATE spend ceiling to the budget guard: the total reserved+actual spend for one video, summed across ALL meters for a given `(run_id, video_index)`, must not exceed the run's `per_video_budget` (the launch setting wired onto `ctx.per_video_budget` in B1a). `reserve()` refuses the call that would breach it. This is independent of the existing per-meter `per_run`/`per_day` ceilings, which must keep working unchanged. Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/sdk/test_budget_per_video.py` (guard-level aggregate enforcement)
- `tests/sdk/test_ctx_per_video_budget.py` (ctx wires video_index + the ceiling)

Keep ALL existing budget tests green (do NOT edit any test): tests/sdk/test_budget.py, test_budget_breach.py, test_budget_estimate.py, test_budget_report.py, test_runner_budget.py, and the integration budget tests.

## Critical invariant — do NOT regress Issue 6 (reserve/release-on-failure)

The reserve/release taxonomy must be preserved: a released reserve (reconcile with `actual=0`) must free the per-video aggregate again (a failed provider call does not leak toward the ceiling), and `record_cost` still records the real cost BEFORE any artifact write. The `_budget_reserved` context manager and `record_cost` behaviour are unchanged. security-auditor will verify this.

## Part 1 — `sdk/sfvf/_budget.py`

- `_TokenState`: add `video_index: int = 0`.
- `_token_states`: when reading a `reserved` entry, set the state's `video_index` from the entry (`int(entry.get("video_index", 0))`); default to 0 when the field is absent (ADDITIVE MIGRATION — old ledgers without the field read as video_index 0, never crash).
- `_record(...)`: add a `video_index: int` parameter and include `"video_index": video_index` in the returned record dict.
- Add a helper `_video_sum(states, run_id, video_index) -> float`: sum `state.effective_amount()` over all states where `state.run_id == run_id and state.video_index == video_index` (across every meter).
- `BudgetGuard.__init__`: add `per_video_ceiling: float | None = None`; store as `self._per_video_ceiling`.
- `reserve(...)`: add a keyword param `video_index: int = 0`. Using the `states`/`amount` already computed, after the existing per-day and per-run checks and before appending the reserved line: if `self._per_video_ceiling is not None`, compute `projected_video = _video_sum(states, run_id, video_index) + amount`; if `_ceiling_breached(projected_video, self._per_video_ceiling)` raise `BudgetExceededError("per-video ceiling exceeded")` (append nothing). Pass `video_index=video_index` into the `_record(...)` for the reserved line.
- `reconcile(...)`: read `video_index` from the matched `reserved` entry (alongside run_id/workflow_id/meter/unit) and pass it into the `_record(...)` for the `actual` line, so both the reserved and actual lines carry `video_index`. Do NOT add a new per-video breach type to `reconcile`'s returned breaches (keep the per_run/per_day breach reporting exactly as is) — the per-video ceiling is enforced at reserve time.

The per-video ceiling applies to whatever `video_index` the reserve is for, including `0` (prepare gets its own aggregate bucket, each video 1..N its own). A `None` ceiling means no per-video cap.

## Part 2 — `sdk/sfvf/context.py`

- `_budget_guard(cfg)`: pass `per_video_ceiling=self.per_video_budget` into the `BudgetGuard(...)` construction (self.per_video_budget was added in B1a).
- `_budget_reserve(...)`: pass `video_index=self.video_index` into the `guard.reserve(...)` call. Nothing else about reserve/reconcile/record_cost changes.

## Deviation from the build plan (intentional, recorded)

The plan listed `app/core/budget_config.py` and a "per-run BudgetConfig view reading per_video_budget". That is NOT needed and is NOT in this increment: `per_video_budget` already reaches the run via `ctx.per_video_budget` (B1a wired it into ContextFile + Context + the supervisor), so enforcement reads it from `ctx` at guard construction — no BudgetConfig field, no supervisor/app change. Do NOT modify `app/core/budget_config.py` or `app/core/supervisor.py`.

## Scope

- sdk/sfvf/_budget.py
- sdk/sfvf/context.py

Do NOT modify: any test, `app/`, `frontend/`, `docs/`, `handoff/`, dependencies.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Additive migration (old ledgers still read). Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_budget_per_video.py tests/sdk/test_ctx_per_video_budget.py tests/sdk/test_budget.py tests/sdk/test_budget_breach.py tests/sdk/test_budget_estimate.py tests/sdk/test_runner_budget.py -q` passes.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/_budget.py sdk/sfvf/context.py` clean, `./.venv/Scripts/python.exe -m ruff format --check .` all formatted, project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary; confirm the reserve/release-on-failure behaviour is unchanged.
