# TASK — MiniMax: clean error on a 200-with-base_resp-failure submit

A frozen RED contract fails: `tests/integration/test_provider_live_fixes.py::test_minimax_raises_a_clean_error_on_a_200_with_base_resp_failure`. MiniMax signals some submit failures with HTTP 200 and `base_resp.status_code != 0` (and no `task_id`); the adapter reads `parse_json(submit, ...)["task_id"]` and raises a raw `KeyError`. It must raise a clean `AdapterError`.

## The fix — `sdk/sfvf/providers/minimax.py`
Replace the single line
```python
        task_id = parse_json(submit, provider="minimax", where="submit")["task_id"]
```
with:
```python
        submit_json = parse_json(submit, provider="minimax", where="submit")
        base_resp = submit_json.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            raise AdapterError(
                "minimax",
                where="submit",
                detail=f"submit rejected (base_resp {base_resp.get('status_code')}: "
                f"{base_resp.get('status_msg') or 'unknown'})",
            )
        task_id = submit_json.get("task_id")
        if not task_id:
            raise AdapterError("minimax", where="submit", detail="no task_id in submit response")
```
`AdapterError` is already imported. Nothing else changes (the poll/download/cost logic is unchanged).

## Scope (ONLY this file)
- `sdk/sfvf/providers/minimax.py`
Do NOT touch any test, other file, docs/, handoff/, requirements, or CI.

## Constraints
- No new dependency. Minimal change. ruff/format/mypy clean on the file.

## Acceptance criteria
1. `python -m pytest tests/integration/test_provider_live_fixes.py` — all pass (the new base_resp test now raises AdapterError).
2. `python -m pytest tests/integration/test_video_minimax.py` — the frozen P-7 contract still passes (its submit returns base_resp status_code 0 + a task_id).
3. `ruff check` + `ruff format --check` + `mypy` clean on `sdk/sfvf/providers/minimax.py`.
4. git diff shows exactly that one file changed.
