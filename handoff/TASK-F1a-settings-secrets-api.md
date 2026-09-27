# TASK F1a — Settings secrets-management API

Satisfies: R-066 (backend). Part of the Settings tab (docs/BUILD_PLAN-settings.md, PRD §8.7).

## Method (RED-first — read this first)
The supervisor has already authored the frozen contract test `tests/api/test_settings_api.py`
(11 tests, currently RED). Your job is to make them pass by adding implementation ONLY.
**Do NOT edit, move, or weaken `tests/api/test_settings_api.py`** — it is the frozen contract.
You may add other tests if useful, but the frozen file must pass unchanged.

## What to build
A GUI-driven way to manage the encrypted API keys (values are never shown), exposed as three
endpoints, plus the app wiring that makes writes possible and take effect without a restart.

### 1. A live, writable secret store on app state (app/main.py)
Today `create_app` resolves secrets once and keeps only the decrypted dict on
`application.state.secrets`; the passphrase is discarded, so nothing can re-encrypt a new key.
- Add an optional parameter `secret_store: SecretStore | None = None` to `create_app`.
- Resolution precedence for the decrypted mapping:
  - if `secrets=` is given -> use it, and `application.state.secret_store = None` (locked: no writes).
  - elif `secret_store=` is given -> `resolved = secret_store.all()` and
    `application.state.secret_store = secret_store` (writable).
  - elif `SFVF_SECRETS_PASSPHRASE` is set -> build `SecretStore(_store_path(), passphrase)`, keep it
    on `application.state.secret_store` (writable), and `resolved = that_store.all()`.
  - else -> `resolved = {}` and `application.state.secret_store = None` (locked).
- Keep the existing `application.state.secrets = dict(resolved)` and the
  `RegistryHolder(..., configured=configured_secret_names(resolved), ...)` construction unchanged.
- Include the new router (below).

### 2. Router: app/api/settings.py (prefix /api), included in app/main.py
- `GET /api/settings` -> JSON:
  - `providers`: for each provider in `sfvf.providers.PROVIDERS`, `{id, label, secret_names (list),
    configured (bool via provider_configured against the CURRENT configured names)}`.
  - `configured_secret_names`: sorted list of names with a non-blank stored value
    (reuse `app.api.workflows.configured_secret_names` over `state.secrets`).
  - `allowed_secret_names`: sorted union of (a) every `PROVIDERS[*].secret_names` and (b) every
    installed workflow's `requires_keys` names (from the registry snapshot / manifests).
  - **Never** include a secret value.
- `PUT /api/settings/secrets/{name}` body `{"value": "..."}`:
  - 409 (value-free message, e.g. "secret store is locked; restart with SFVF_SECRETS_PASSPHRASE to
    edit keys") if `state.secret_store is None`.
  - 400/422 if `name` not in `allowed_secret_names`, or if `value` is missing/empty/whitespace.
  - else `secret_store.set(name, value)`, then REFRESH (see 3), return 200 (e.g. the provider's new
    configured status).
- `DELETE /api/settings/secrets/{name}`:
  - 409 if locked.
  - else `secret_store.delete(name)` wrapped to be **idempotent** — `SecretStore.delete` raises
    `KeyError` on a missing name (app/core/secrets.py:59); catch it and treat as success. Then
    REFRESH, return 200.

### 3. Refresh after every successful mutation (no restart)
After a successful set/delete:
- `application.state.secrets = dict(secret_store.all())`
- rebuild the registry so capabilities recompute:
  `application.state.registry = RegistryHolder(state.registry.workflows_dir,
   configured=configured_secret_names(state.secrets),
   disabled_web_tiers=state.disabled_web_tiers, budget=state.budget)`
  (RegistryHolder is in app/api/workflows.py; it freezes `_offered` at construction, so a fresh
  instance is the way to pick up a newly configured provider — this is what makes
  `test_put_secret_makes_provider_configured_without_restart` pass for both /api/settings and
  /api/providers.)

## Constraints
- Workspace only; do not touch anything outside E:\pk02k02s02-short-form-video-factory\Workspace.
- Do not add dependencies. Match existing style (app/api/providers.py is the closest sibling).
- New endpoints inherit the existing csrf_guard middleware — no auth changes.

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/api/test_settings_api.py -q` passes (all 11), and the
  full `tests/api` suite still passes.
- `./.venv/Scripts/python.exe -m ruff check .` and `-m ruff format --check .` and `-m mypy` are clean.
- You did NOT modify tests/api/test_settings_api.py.
- **Assumed, not verified:** list every fact you relied on that the brief/code did not settle
  (what, why, what would confirm it), or write `none`.
