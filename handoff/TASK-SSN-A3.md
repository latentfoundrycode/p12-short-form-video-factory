# TASK-SSN-A3 — app-side library access + read endpoints

Give the app read access to the owner library pool and back the Library tab's list view with two endpoints. Pinned by `tests/api/test_library_api.py` (make it green without editing it).

## What to implement

### 1. `create_app` gains a `library_dir` param (`app/main.py`)

- Add a keyword-only `library_dir: Path | None = None` to `create_app(...)` (alongside `runs_dir` etc.).
- Store it on app state: `application.state.library_dir = library_dir or LIBRARY_DIR` (import `LIBRARY_DIR` from `app.paths`, mirroring how `runs_dir` is defaulted/stored).
- Register the new library router (below): `application.include_router(library_router)` where the others are registered.

### 2. New router `app/api/library.py` (prefix `/api`, mirror the style of `app/api/learning.py`)

- **`GET /api/library/assets`** -> `{"assets": [ {"id": str, "kind": str, "status": str, "facets": dict, "description": str, "grant": <grant>}, ... ]}`.
  - The owner pool is `request.app.state.library_dir / "_owner"`. If that directory does not exist, return `{"assets": []}`.
  - Otherwise list ALL statuses: `LibraryStore(owner_root).find(status=None)` (construct the store with default facets — reading needs no facet vocabulary). For each asset build a row from its descriptor (`id`, `kind`, `status`, `facets`, `description`) and attach `grant = GrantStore(owner_root).get_grant(asset.id)` (default-deny `{"workflows": []}` for an ungranted asset — `GrantStore` already returns that).
  - Deterministic order (e.g. by `id`, or reuse `find`'s order).
- **`GET /api/library/workflows`** -> `{"workflows": [ {"id": str, "label": str}, ... ]}` for the grant picker.
  - Read the registry snapshot the same way `app/api/workflows.py` / `learning.py` do (`_holder(request).snapshot` or the equivalent). `id` = the workflow's manifest id; `label` = the workflow's manifest `name`.

Use `LibraryStore` from `sfvf.library` and `GrantStore` from `sfvf.grants`. Use Pydantic response models like the other routers (`*Out`), or plain dicts if that matches the router style better — match `learning.py`. GET routes are CSRF-exempt (safe methods); no auth/token handling here.

## Scope

- `app/main.py`
- `app/api/library.py` (new)

Touch nothing else. Do NOT modify any test, the SDK (`sdk/`), anything under `docs/` or `handoff/`, `.env`, `secrets/`, or CI. Do NOT add dependencies.

## Constraints

- Workspace boundary; ASCII; one paragraph is one line.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_library_api.py -q` passes (5).
- No regression: `./.venv/Scripts/python.exe -m pytest tests/api -q`.
- `./.venv/Scripts/python.exe -m ruff check app/main.py app/api/library.py` and `./.venv/Scripts/python.exe -m mypy app/main.py app/api/library.py` are clean.
- Print the files you changed and a one-paragraph summary.
