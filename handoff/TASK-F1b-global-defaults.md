# TASK F1b — Settings global-defaults store, resolvers, and run-path wiring

Backend for R-068 (the Settings tab's global defaults; the UI is F1c). RED-first: the frozen tests
`tests/core/test_app_settings.py` and the `defaults` tests in `tests/api/test_settings_api.py` exist
and are RED. **Do NOT edit those test files.** Implement to make them pass.

## 1. app/core/app_settings.py (new)
A JSON store for the four PRD §8.7 global defaults, under DATA_ROOT.
- Dataclass `AppSettings` with fields: `silence_limit_seconds: float`, `default_concurrency: int`,
  `default_step_concurrency: int`, `cache_max_bytes: int`.
- Built-in defaults: `silence_limit_seconds = DEFAULT_SILENCE_SECONDS` (import from
  app.core.supervisor), `default_concurrency = 1`, `default_step_concurrency = 1`,
  `cache_max_bytes = DEFAULT_CACHE_MAX_BYTES` (import from app.core.cache_config).
- **Store path read at CALL time:** `import app.paths as paths` and use `paths.DATA_ROOT / "app_settings.json"`
  inside the functions (NOT `from app.paths import DATA_ROOT`), so tests that monkeypatch
  `app.paths.DATA_ROOT` take effect.
- `load() -> AppSettings`: read the JSON; a missing file, unreadable/corrupt JSON, or an
  individual field that is missing/invalid falls back to that field's default. **Never raises.**
- `update(**fields) -> AppSettings`: load current, apply the given fields, VALIDATE, persist
  (atomic write — tempfile + os.replace), return the new AppSettings. Validation (raise `ValueError`):
  `silence_limit_seconds` finite and > 0; `default_concurrency`/`default_step_concurrency` ints >= 1;
  `cache_max_bytes` int >= 1. (Bools are not valid ints.)
- Resolvers, precedence **explicit env var > stored setting > built-in default**, env parsed
  leniently (an unset/invalid env value falls through to stored/default, matching cache_config):
  - `silence_limit_seconds() -> float`  (env `SFVF_SILENCE_LIMIT_SECONDS`)
  - `default_concurrency() -> int`      (env `SFVF_DEFAULT_CONCURRENCY`)
  - `default_step_concurrency() -> int` (env `SFVF_DEFAULT_STEP_CONCURRENCY`)
  - `cache_max_bytes() -> int`          (env `SFVF_CACHE_MAX_BYTES`)
  Also a helper for the API, e.g. `effective_defaults() -> dict[str, dict]` giving each field's
  `{"effective": <value>, "source": "env"|"stored"|"default"}`.

## 2. app/core/cache_config.py
Keep the public `cache_max_bytes()` name/signature (app/core/supervisor.py imports it) but delegate
to `app_settings.cache_max_bytes()` so a stored ceiling is honoured (env still wins). Keep
`DEFAULT_CACHE_MAX_BYTES` where it is. Avoid an import cycle (app_settings imports the default
constant from cache_config; cache_config calls app_settings at call time inside the function body).

## 3. app/api/runs.py — admit_run consumes the stored defaults (the point of F1b, plan-critic B3)
Add optional params `silence_limit_default: float | None = None` and `step_concurrency: int | None = None`
to `admit_run`. When None, resolve from `app_settings.silence_limit_seconds()` /
`app_settings.default_step_concurrency()`. Pass both into the `run_request(...)` call
(`run_request` already accepts `silence_limit_default=` and `step_concurrency=`). Do not change the
`concurrency` param (it stays caller-provided; its stored default seeds the launch form in F1c).

## 4. app/api/settings.py — the defaults endpoints
- Extend `GET /api/settings`: add `"defaults": app_settings.effective_defaults()` (each field's
  effective value + source). Still no secret values.
- Add `PUT /api/settings/defaults` accepting a partial body of the four fields; validate via
  `app_settings.update(**provided)`; a `ValueError` -> 400 or 422. Return 200.

## Done when
- `./.venv/Scripts/python.exe -m pytest tests/core/test_app_settings.py tests/api/test_settings_api.py -q` -> all pass.
- Full `tests/api` and `tests/core` still pass (ignore the two pre-existing httpx `..`-path failures).
- `ruff check .`, `ruff format --check .`, `mypy` clean. Frozen test files unmodified.
- End with an `Assumed, not verified` list (or `none`).
