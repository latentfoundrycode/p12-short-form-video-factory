# TASK F1b-fix — reject bool / non-int for the global defaults

Review B blocker. RED-first: new frozen tests are in place and RED
(test_app_settings.py::test_update_rejects_bool, ::test_update_rejects_noninteger_float_for_int_fields;
test_settings_api.py::test_put_defaults_rejects_bool). Do NOT edit test files.

## The bug
Pydantic lax mode coerces JSON `true` -> `1`/`1.0` before the handler, and `app_settings.update()`
casts with `int()/float()` before `_validate`, so a bool (or a fractional float for an int field)
slips through. `PUT /api/settings/defaults {"cache_max_bytes": true}` returns 200 and stores `1`.

## Fix (both layers must reject a bool BEFORE any numeric cast)

1. `app/api/settings.py` — `DefaultsUpdateIn`: reject a bool for every field. Add a field
   validator (e.g. one `@field_validator("silence_limit_seconds","default_concurrency",
   "default_step_concurrency","cache_max_bytes", mode="before")`) that raises if
   `isinstance(v, bool)`. Keep the `int|float|None` shapes for the non-bool path.

2. `app/core/app_settings.py` — `update(**fields)`: before casting, validate each supplied raw
   value and raise `ValueError` for:
   - any field whose value `isinstance(v, bool)`;
   - an int field (`default_concurrency`, `default_step_concurrency`, `cache_max_bytes`) whose value
     is not an `int` (reject a float like `2.9` rather than truncating it);
   - `silence_limit_seconds` that is not an `int`/`float`.
   Then proceed to the existing numeric validation (finite/positive; ints >= 1). Do this on the raw
   supplied `fields`, not on the merged/cast object.

## Done when
- ./.venv/Scripts/python.exe -m pytest tests/core/test_app_settings.py tests/api/test_settings_api.py tests/core/test_cache_config.py -q -> all pass.
- ruff check ., ruff format --check ., mypy clean. Frozen test files unmodified.
- End with an `Assumed, not verified` list (or `none`).
