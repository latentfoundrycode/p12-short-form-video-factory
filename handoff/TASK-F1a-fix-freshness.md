# TASK F1a-fix — Settings freshness for long-lived consumers + value hygiene

Follow-up to F1a (R-066). Cross-family Review B found a real correctness gap and two advisories.
RED-first: new frozen tests are already in `tests/api/test_settings_api.py` (3 currently RED:
`test_put_preserves_state_secrets_identity`, `test_delete_preserves_state_secrets_identity`,
`test_put_strips_surrounding_whitespace`). **Do NOT edit the test file.** Make them pass by
changing implementation only.

## The bug (blocker)
`app/api/settings.py::_refresh_secrets` currently does `request.app.state.secrets = dict(store.all())`
— it REBINDS `state.secrets` to a new object. But the scheduler lifespan
(`app/main.py`, the `enable_scheduler` branch) captures `scheduler_app.state.secrets` and the
registry BY REFERENCE at startup into `SchedulerDeps`, and `resolve_workflow` closes over the
startup `holder`. So after a Settings key change, scheduled (unattended) runs keep using the
startup secrets and startup registry until the app restarts.

## Fixes

1. **`app/api/settings.py::_refresh_secrets` — mutate `state.secrets` in place.**
   Replace the rebind with an in-place update so any long-lived capture of that dict stays current:
   ```python
   current = request.app.state.secrets
   current.clear()
   current.update(store.all())
   ```
   Keep rebuilding `request.app.state.registry` as a fresh `RegistryHolder` (unchanged).

2. **`app/main.py` scheduler lifespan — read the registry fresh at fire time.**
   Change `resolve_workflow` so it reads `scheduler_app.state.registry` on each call instead of the
   `holder` captured once at lifespan start:
   ```python
   def resolve_workflow(workflow_id: str) -> Path | None:
       holder = scheduler_app.state.registry  # fresh: rebuilt when a key is set via Settings
       entry = holder.get(workflow_id)
       if entry is None or any(p.severity == "error" for p in entry.problems):
           return None
       return entry.path
   ```
   Leave `scheduler_secrets = scheduler_app.state.secrets` as-is — with fix (1) it now stays live
   because it is the same dict object, mutated in place. (Do not otherwise change SchedulerDeps.)

3. **`app/api/settings.py` — strip surrounding whitespace and use SecretStr (defense-in-depth).**
   Type the request field as pydantic `SecretStr` and store the stripped secret:
   ```python
   from pydantic import SecretStr, field_validator
   class SecretValueIn(BaseModel):
       value: SecretStr
       @field_validator("value")
       @classmethod
       def non_blank(cls, value: SecretStr) -> SecretStr:
           if not value.get_secret_value().strip():
               raise ValueError("value must not be blank")
           return value
   ```
   In `put_secret`, store `body.value.get_secret_value().strip()`. (SecretStr keeps the value out of
   422 error echoes, tracebacks, and logs; the strip makes `"  key  "` store as `"key"`.)

4. **`docs/HARDENING.md` — record (do not fix) the store race.** Add under the Settings section:
   `H-SETTINGS-2 — SecretStore.set/delete is an unlocked read-modify-write, now reachable over HTTP;
   two overlapping PUT/DELETE requests could drop a key. Single-user local, low; a fix serializes
   store mutations (a lock or a single-writer). _Source: F1a Review B advisory._`

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api/test_settings_api.py -q` -> all 14 pass.
- Full `tests/api` still passes (the two pre-existing httpx `..`-path failures may remain — leave them).
- `ruff check .`, `ruff format --check .`, `mypy` clean. Frozen test file unmodified.
- End with an `Assumed, not verified` list (or `none`).
