# TASK S2a — least-privilege secret injection + strip passphrase from ALL subprocesses

**Builder:** Cursor. **Product code only.** Touch `app/main.py`, `app/api/runs.py`, `app/core/supervisor.py`,
`app/core/secrets.py`, `app/core/env.py`. Do NOT touch `tests/`, `docs/`, `handoff/`. The reviewer contract
`tests/api/test_secret_injection.py` is FROZEN.

Wire the §5.6 store into the run pipeline with **least privilege** and make sure the master passphrase never
reaches any child process. (This supersedes an earlier whole-store version — inject only allowlisted keys.)

## 1. `app/core/secrets.py` — shared subprocess-env helper

Add a public helper (used by both the supervisor and env setup):
```python
def subprocess_env() -> dict[str, str]:
    """os.environ minus the master passphrase — for any subprocess we spawn (§5.6 / H17)."""
    return {k: v for k, v in os.environ.items() if k != "SFVF_SECRETS_PASSPHRASE"}
```
(`import os` already present.)

## 2. `app/main.py` — load the store at startup (unchanged from before)

`create_app(..., secrets: Mapping[str, str] | None = None)`: injected mapping wins; else if
`SFVF_SECRETS_PASSPHRASE` is set/non-empty, load `SecretStore(store_path, passphrase).all()` (path from
`SFVF_SECRETS_PATH` else the `secrets` default — reuse `_store_path`); else `{}`. A `SecretsError` propagates
(fail-fast startup). `application.state.secrets = dict(resolved)`.

## 3. `app/api/runs.py` — thread it (unchanged)

`_secrets(request) -> Mapping[str, str]` mirroring `_ensure_env`/`_popen`; pass `secrets=_secrets(request)` into
`admit_run(...)`.

## 4. `app/core/supervisor.py` — ALLOWLISTED injection + passphrase strip

- `admit_run`/`run_request` take `secrets: Mapping[str, str] | None = None` (coerce `dict(secrets or {})`).
- The manifest is already parsed in `run_request` (`parse_manifest_toml(...)`). Compute the allowlist from the
  workflow's declared keys and inject **only those**:
  ```python
  allowed = {rk.name for rk in manifest.requires_keys}
  injected = {k: v for k, v in (secrets or {}).items() if k in allowed}
  ```
  Put `injected` on `_ContextWiring.secrets` (add the `secrets: dict[str, str]` field). `_make_context` writes
  `secrets=dict(wiring.secrets)` into every `context.json`. **Do NOT inject the whole store** — a workflow gets
  only the keys it declared in `[[requires_keys]]` (least privilege).
- In `_start_runner`, pass `env=subprocess_env()` (import from `app.core.secrets`) to the `popen(...)` call, so
  the runner subprocess never inherits the passphrase.

## 5. `app/core/env.py` — strip passphrase from env-setup subprocesses (HARDENING H17, HIGH)

The venv/`pip install` subprocesses currently inherit the full environment, so workflow-declared dependency
build code could read `SFVF_SECRETS_PASSPHRASE`. Fix the choke point `_run_timed` (and
`default_find_python`'s `subprocess.run`): pass `env=subprocess_env()` (import from `app.core.secrets`). All
env-setup spawns then run without the master passphrase.

Never log a secret value or the passphrase. mypy-strict clean. No new dependency.

## Acceptance

`tests/api/test_secret_injection.py` passes (6 tests): only the `[[requires_keys]]`-allowlisted secret reaches
`context.json` (others withheld); a workflow with no required keys gets `{}`; `subprocess_env()` strips the
passphrase while keeping other env; `env._run_timed` spawns with `env=` excluding the passphrase; `create_app`
loads the store when the passphrase is set; no passphrase → empty. Existing `tests/api/test_runs.py` and the
env tests still pass.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/api/test_secret_injection.py tests/api/test_runs.py tests/core/test_env.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
