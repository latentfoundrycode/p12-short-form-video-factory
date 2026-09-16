# TASK — expose declared workflow params in the workflows API

## Goal (one sentence)
Serialize each workflow's declared `[[params]]` into the `/api/workflows` response so the frontend
launcher can render a typed form (with declared defaults) instead of a raw-JSON textarea.

## Why
The current "minimal launcher" makes the user hand-write a JSON params object and does NOT apply
declared defaults, so a workflow that reads a defaulted param (e.g. `ctx.params["duration_s"]`,
default 30) crashes when the user omits it. Exposing the declared param specs lets the launcher
pre-fill defaults and validate types.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_workflows.py` — `WORKFLOW_FIELDS` now includes `"params"`, plus
`test_declared_params_are_exposed_with_defaults`, `test_workflow_without_params_has_empty_params`,
`test_broken_workflow_has_empty_params`. All existing workflow tests must stay green.

## What to change — `app/api/workflows.py` only
1. Add a `ParamOut(BaseModel)` with EXACTLY these fields (matching the test's `PARAM_FIELDS`):
   `key: str`, `type: str`, `label: str`, `required: bool`, `default: Any`, `help: str | None`,
   `affects_cost: bool`, `min: float | None`, `max: float | None`, `step: float | None`,
   `options: list[Any] | None`, `options_from: str | None`, `placeholder: str | None`,
   `unit: str | None`. (Note: the source `Param` model also has `accept`; do NOT include it here —
   the field set must equal `PARAM_FIELDS`.) Import `Any` from `typing`.
2. Add `params: list[ParamOut]` to `WorkflowOut`.
3. In `_serialize`, populate it: `[]` when `manifest is None`, else one `ParamOut` per
   `manifest.params` IN DECLARATION ORDER, copying each field straight from the source `Param`
   (`app/registry/schema.py:Param`). `type` is the `ParamType` string value — assign it directly
   (it serializes to its string).

## Constraints / do-nots
- Touch ONLY `app/api/workflows.py`. Do NOT edit any test or other file.
- Do not change any existing field or endpoint behaviour.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/api/workflows.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_workflows.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
