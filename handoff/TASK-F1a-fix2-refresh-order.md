# TASK F1a-fix2 — refresh must decrypt before wiping the live secret map

Follow-up to F1a-fix (R-066). Review B (cross-family) blocker. RED-first: the frozen test
tests/api/test_settings_api.py::test_refresh_failure_leaves_previous_secrets_intact is RED.
Do NOT edit the test file.

## The bug
`app/api/settings.py::_refresh_secrets` does `current.clear()` and THEN `current.update(store.all())`.
`store.all()` is a full scrypt decrypt (~0.24s), so app.state.secrets (the SAME dict the scheduler
lifespan captured by reference) is EMPTY for that whole interval — a scheduled tick landing there
injects no secrets — and if `store.all()` raises after `clear()`, the map stays empty until restart.

## Fix (app/api/settings.py::_refresh_secrets)
Decrypt FIRST, then publish into the existing object, so the map is never transiently empty and a
failed reload leaves the previous contents intact:
```python
def _refresh_secrets(request: Request, store: SecretStore) -> None:
    loaded = store.all()          # decrypt BEFORE mutating; if this raises, state is untouched
    current = request.app.state.secrets
    current.clear()
    current.update(loaded)
    registry = _holder(request)
    request.app.state.registry = RegistryHolder(
        registry.workflows_dir,
        configured=configured_secret_names(request.app.state.secrets),
        disabled_web_tiers=request.app.state.disabled_web_tiers,
        budget=request.app.state.budget,
    )
```

## Also (docs/HARDENING.md, H-SETTINGS-1 wording)
The current note says a post-write learning run is "refused". Correct it to cover rotate/delete too:
the learning optimizer + `make_openrouter_completion` read the STARTUP secret snapshot, so a key
ADDED after startup is missing (path refused), but a key ROTATED or DELETED still uses the OLD
startup value — a later learning completion can still spend with a stale/rotated credential until
restart. Update the H-SETTINGS-1 sentence accordingly (keep it one entry).

## Done when
- ./.venv/Scripts/python.exe -m pytest tests/api/test_settings_api.py -q -> all 15 pass.
- ruff check ., ruff format --check ., mypy clean. Frozen test file unmodified.
- End with an `Assumed, not verified` list (or `none`).
