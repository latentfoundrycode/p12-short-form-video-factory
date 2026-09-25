# TASK-SSN-A1 — LibraryStore.deactivate / reactivate (the "inactive" status)

Add owner-facing "hide" to the content-addressed library store: an asset can be DEACTIVATED (hidden from the default listing) and REACTIVATED, without ever deleting its content. This is the store-level primitive behind the Library tab's "remove" (which means hide, not erase).

## What to implement

In `sdk/sfvf/library.py`, add two methods to `LibraryStore` and support a new status value `"inactive"`:

- `deactivate(self, asset_id: str) -> Asset` — flip the asset's status to `"inactive"` and return the updated `Asset`.
- `reactivate(self, asset_id: str) -> Asset` — flip the asset's status back to `"active"` and return the updated `Asset`.

Requirements (all pinned by the frozen test `tests/sdk/test_library_deactivate.py` — make it green without editing it):

- **Metadata-only, id-targeted.** Like `annotate`, these read the sidecar by id (never alias-resolved), rewrite the authoritative sidecar atomically, and refresh the derived `catalog.json`. The id, the blob, and the content are unchanged. Do NOT delete any blob or sidecar.
- **The new status is `"inactive"`**, distinct from the existing `"active"` and `"superseded"`. `find()` already filters by exact status, so `find()` (default `status="active"`) hides an inactive asset, `find(status="inactive")` returns it, and `find(status=None)` returns any status — this should follow from the status flip plus the existing `find`; verify it does and adjust only if needed.
- **Idempotent.** Deactivating an already-inactive asset (or reactivating an already-active one) is not an error; the status stays as set.
- **Unknown id raises `LibraryError`** (mirror `annotate`'s "unknown asset"). A name/alias passed instead of an id does not resolve and therefore raises (these methods are id-targeted).
- **`get(id)` reflects the new status** after the flip; the catalogue entry is refreshed so `find` is consistent (mirror how `annotate` / supersession refresh the catalogue).

Reuse the existing patterns in the file (`_read_sidecar`, `_write_sidecar`, the supersession status-flip in `_apply_supersession`, `rebuild_catalog` / the catalogue refresh). Keep the change minimal and consistent with the surrounding code.

## Scope

- `sdk/sfvf/library.py`

Touch nothing else. Do NOT modify any test, anything under `docs/` or `handoff/`, `.env`, `secrets/`, or CI configuration. Do NOT add dependencies.

## Constraints

- The workspace boundary: read and write only inside this `Workspace/` checkout.
- ASCII only; one paragraph is one line (no hard wraps inside a paragraph).
- Record any tooling friction or a defect you notice in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_library_deactivate.py -q` passes (all 8).
- The existing library tests still pass: `./.venv/Scripts/python.exe -m pytest tests/sdk -q`.
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/library.py` and `./.venv/Scripts/python.exe -m mypy` are clean.
- Print the list of files you changed and a one-paragraph summary.
