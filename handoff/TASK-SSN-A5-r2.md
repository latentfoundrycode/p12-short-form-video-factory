# TASK-SSN-A5-r2 — expose a public grant validator (hygiene)

All three reviewers flagged that the upload endpoint imports the private `sfvf.grants._validate_grant` across a module boundary. Make the validator public and switch the endpoint to it. Behaviour is unchanged; pinned by `tests/sdk/test_grants.py::test_validate_grant_is_public` (already committed) plus the existing grants + upload tests staying green.

## What to implement

1. `sdk/sfvf/grants.py`: expose the grant-shape validator publicly as `validate_grant(grant) -> dict` — rename the existing private `_validate_grant` to `validate_grant` and update its internal call sites (in `GrantStore.set_grant` and anywhere else it is used) to the public name. Do not change the validation logic or its `GrantError` behaviour. (A back-compat alias is not required — there are no external callers of the private name except the endpoint you are about to switch.)
2. `app/api/library.py`: change the import and use-site from `_validate_grant` to the public `validate_grant`.

## Scope

- `sdk/sfvf/grants.py`
- `app/api/library.py`

Touch nothing else. Do NOT modify tests, other files, docs, handoff, CI, or dependencies.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_grants.py tests/api/test_library_upload.py -q` passes.
- No regression: `./.venv/Scripts/python.exe -m pytest tests/sdk tests/api -q` (the two pre-existing `tests/api` failures are unrelated).
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/grants.py app/api/library.py` and the project `./.venv/Scripts/python.exe -m mypy` are clean (only the pre-existing PIL error remains).
- Print the files you changed and a one-paragraph summary.
