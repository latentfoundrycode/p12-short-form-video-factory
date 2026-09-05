# TASK S2a — load secrets at startup, inject into context.json, strip passphrase from subprocess env

**Builder:** Cursor. **Product code only.** Touch `app/main.py`, `app/api/runs.py`, `app/core/supervisor.py`.
Do NOT touch `tests/`, `docs/`, `handoff/`, or `app/core/secrets.py`. The reviewer contract
`tests/api/test_secret_injection.py` is FROZEN.

Wire the §5.6 secret store (S1) into the run pipeline: load it at app start, inject the permitted secrets into
every `context.json`, and make sure the master passphrase never reaches a workflow subprocess (HARDENING H17).
Mirror the existing `ensure_env`/`popen` injection pattern exactly.

## 1. `app/main.py` — load the store at startup

- `create_app(..., secrets: Mapping[str, str] | None = None)` (new keyword-only param alongside `ensure_env`/
  `popen`). Resolve the secrets mapping:
  - if `secrets is not None`: use it as-is;
  - else if `os.environ.get("SFVF_SECRETS_PASSPHRASE")` is set (non-empty): load
    `SecretStore(store_path, passphrase).all()` where `store_path` comes from `SFVF_SECRETS_PATH` else the
    `SecretStore` default (reuse `app.core.secrets`'s path logic — import a helper or replicate the same
    `SFVF_SECRETS_PATH`/default). A `SecretsError` here should propagate (fail fast at startup — a wrong
    passphrase must not start silently);
  - else: `{}`.
- Store it on `application.state.secrets = dict(resolved)`.

## 2. `app/api/runs.py` — thread it to admission

- Add a `_secrets(request) -> Mapping[str, str]` accessor mirroring `_ensure_env`/`_popen`
  (`getattr(request.app.state, "secrets", None)` → `{}` if absent).
- Pass `secrets=_secrets(request)` into the `admit_run(...)` call.

## 3. `app/core/supervisor.py` — inject + strip passphrase

- `admit_run(..., secrets: Mapping[str, str] = {})` — accept the mapping (use a safe default, e.g.
  `secrets: Mapping[str, str] | None = None` then `secrets = secrets or {}`; do NOT use a mutable default
  literal that ruff/B006 would flag).
- Add `secrets: dict[str, str]` to the `_ContextWiring` dataclass, and set it when the wiring is built in
  `admit_run` (from the `secrets` param, as `dict(secrets)`).
- In `_make_context`, change `secrets={}` to `secrets=dict(wiring.secrets)` so every `context.json`
  (prepare + per-video) carries the permitted secrets.
- Add `def _subprocess_env() -> dict[str, str]: return {k: v for k, v in os.environ.items() if k !=
  "SFVF_SECRETS_PASSPHRASE"}` and pass `env=_subprocess_env()` in the `popen(...)` call inside `_start_runner`.
  (`import os` if not already imported.) This is H17: the workflow subprocess gets its secrets from
  `context.json`, never the master passphrase from the environment.

Never log/print a secret value or the passphrase. mypy-strict clean. No new dependency.

## Acceptance

`tests/api/test_secret_injection.py` passes (6 tests): loaded secrets appear in `context.json`; no secrets →
`{}`; `_subprocess_env()` strips `SFVF_SECRETS_PASSPHRASE` while keeping other env; `create_app` loads the
store when the passphrase env is set; `create_app` with no passphrase → empty. The existing `tests/api/
test_runs.py` and the rest of the suite still pass (the new `create_app` param + `admit_run` param are additive
with safe defaults).

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_secret_injection.py tests/api/test_runs.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
