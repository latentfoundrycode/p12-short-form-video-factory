# TASK-SSN-A8-r3 — Remove asserts (ruff S101) from the owner-pool guards

A8-r2 is functionally correct and all tests pass, but it introduced two `assert` statements in `sdk/sfvf/context.py` (lines ~384 and ~404) for mypy narrowing, which ruff flags as S101 (use of `assert` in non-test code). Remove them without changing behaviour. Fix ONLY `sdk/sfvf/context.py`. Do NOT edit any test. Keep all currently-passing tests green.

## Fix

Narrow the types with explicit `is None` checks (which mypy flow-narrows) instead of `assert`. In `find()` and `_granted_owner_asset()`, replace the `_owner_pool_ready()` call + `assert owner_pool is not None and grants is not None` pattern with an inline guard that binds locals and checks None + existence in one condition, e.g.:

```
owner_pool = self._owner_pool
grants = self._grants
root = self._owner_pool_root
if owner_pool is None or grants is None or root is None or not root.exists():
    return own            # find(): return own ; _granted_owner_asset(): return None
```

Then use the narrowed `owner_pool` / `grants` locals. You may keep or drop the `_owner_pool_ready()` helper — if you keep it, it must not be the thing mypy relies on for narrowing (the inline `is None` checks are). No `# noqa`. Preserve the exact behaviour: owner pool consulted only when its root exists; `find()` returns own-only otherwise; `_granted_owner_asset` returns None otherwise; the `inactive` withhold and grant check are unchanged.

## Scope

- sdk/sfvf/context.py

Do NOT modify: any test, `app/`, `frontend/`, `docs/`, `handoff/`, dependencies.

## Done when

- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/context.py` clean (no S101), and project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_ctx_library_grants.py tests/sdk/test_ctx_library.py tests/sdk/test_ctx_library_hardening.py tests/core/test_supervisor_library_owner_pool.py -q` passes.
- Print the file you changed and a one-line summary.
