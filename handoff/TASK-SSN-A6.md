# TASK-SSN-A6 — library edit / grant / deactivate endpoints

Add the mutating endpoints behind the Library tab's detail pane, in `app/api/library.py`. Pinned by `tests/api/test_library_mutations_api.py` (make it green without editing it).

## What to implement (all in `app/api/library.py`)

Owner root = `request.app.state.library_dir / "_owner"`. For each endpoint, FIRST resolve the asset in the owner pool (`LibraryStore(owner_root).get(asset_id)`); if it does not resolve, return **404** — this cleanly separates "unknown asset" (404) from "bad input" (422). Then perform the operation and return the updated asset row (`_asset_row`, the same {id,kind,status,facets,description,grant} shape as GET).

- **`PUT /api/library/assets/{asset_id}`** — JSON body `{"facets"?: dict[str,str], "caveats"?: str}`. Call `LibraryStore(owner_root, facets=(FacetSpec("mood"), FacetSpec("energy"))).annotate(asset_id, caveats=..., facets=...)` (pass only the fields supplied). A facet outside the declared vocab raises `LibraryError` -> map to **422**. Return the updated row (grant unchanged, read via `GrantStore.get_grant`).
- **`POST /api/library/assets/{asset_id}/grant`** — JSON body is the grant itself (`{"all": true}` or `{"workflows": [ids]}`). Validate with the public `validate_grant` (from `sfvf.grants`); a malformed grant -> **400/422**. Then `GrantStore(owner_root).set_grant(asset_id, grant)`. Return the updated row.
- **`POST /api/library/assets/{asset_id}/deactivate`** and **`POST /api/library/assets/{asset_id}/reactivate`** — call `LibraryStore(owner_root).deactivate(asset_id)` / `reactivate(asset_id)`. Return the updated row.

**Path safety on `asset_id`**: an asset id is a sha256 hex string. Validate it (reject anything that is not a valid id / safe segment) and treat an invalid id as **404** — the id must never be usable to escape the owner pool (it flows into `items/<id>.json`). Reuse the SDK's id check if one is exported, else validate it is 64 lowercase hex chars.

These are mutating (PUT/POST) routes; the global `Sec-Fetch-Site` CSRF guard already covers them (same-origin). No token handling here.

## Scope

- `app/api/library.py`

Touch nothing else. Do NOT modify tests, the SDK, docs, handoff, CI, or dependencies.

## Constraints

- Workspace boundary; ASCII; one paragraph is one line.
- Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_library_mutations_api.py -q` passes (7).
- No regression: `./.venv/Scripts/python.exe -m pytest tests/api -q` (the two pre-existing `test_clear_runs`/`test_learning_run_api` failures are unrelated).
- `./.venv/Scripts/python.exe -m ruff check app/api/library.py` and the project `./.venv/Scripts/python.exe -m mypy` are clean (only the pre-existing PIL error).
- Print the files you changed and a one-paragraph summary.
