# TASK — web-image-sourcing inc6 FIX round 12: a blank stored secret is not "configured"

## Why this round
Cross-family review (P2): `provider_configured`/`capabilities_offered` gate on secret-NAME presence
(`all(name in configured for name in provider.secret_names)`). The app builds `configured` from
`set(resolved)` — the secret NAMES — so a stored secret whose VALUE is empty or whitespace still marks
its provider "configured" and offers its capability (e.g. `web.images.web`) at scan time. At runtime
the serpapi adapter refuses an empty key (`if not key: raise`). Result: a blank `SERPAPI_API_KEY`
advertises the paid web tier, then every search fails — the same advertise-then-fail class as the
off-switch (R7) and budget-ceiling (R8) gaps.

Fix: the app must treat only secrets with a non-blank value as configured when it computes offered
capabilities. (Keyless providers — e.g. Openverse/commons, `secret_names=()` — are unaffected:
`all(()) == True` regardless, so `web.images.commons` stays offered.)

A frozen RED contract is committed (HEAD): `tests/api/test_configured_secrets.py`.

## Changes (two files)

### 1. `app/api/workflows.py` — the helper
Add a module-level function:
```python
def configured_secret_names(secrets: Mapping[str, str]) -> set[str]:
    """Secret names whose stored VALUE is non-blank. A blank/whitespace value is not a usable
    credential, so its provider must not be treated as configured for capability availability
    (otherwise the capability is offered at scan time but refused at runtime)."""
    return {name for name, value in secrets.items() if isinstance(value, str) and value.strip()}
```
Import `Mapping` from `collections.abc` if not already imported.

### 2. `app/main.py` — use it for the registry's `configured`
Where the registry is built (~line 106), replace `configured=set(resolved)` with
`configured=configured_secret_names(resolved)` (import the helper from `app.api.workflows`). This is
the only behavioural change: `application.state.secrets = dict(resolved)` (the runtime injection dict)
stays the FULL resolved map — the runtime already fail-closes on an empty value — so only scan-time
availability is tightened.

## Scope
Only `app/api/workflows.py` and `app/main.py`. Do NOT change the SDK `provider_configured`/
`capabilities_offered` (they correctly take a name-set), the serpapi adapter, media.web, the registry
vocabulary, or the frozen tests. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/api/test_configured_secrets.py tests/api/test_registry_offswitch.py -q` → all pass.
- Broader app suite via the project venv (subprocess tests need `sfvf` installed):
  `.\.venv\Scripts\python.exe -m pytest tests/api tests/registry tests/core -q` → all pass. If an
  existing test stored a blank secret expecting a capability offered, it was relying on the bug —
  report it, do NOT edit a frozen test.
- `ruff check .` and `ruff format --check .` clean; `.\.venv\Scripts\python.exe -m mypy` clean.
  Create no notes/docs files.
