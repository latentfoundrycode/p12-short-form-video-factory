# TASK D-3a — library value assets + annotate + supersession (SDK §7.5-7.7)

## Goal (one sentence)
Add the library's descriptor-mutating store operations: JSON `value` assets (`put_value`/`value`),
in-place `annotate`, and supersession status-flips on `put`/`put_value`.

## Frozen contract (already committed — do NOT edit any test)
`tests/sdk/test_library_mutations.py`. Frozen signatures in `sdk/sfvf/library.py`:
`put_value(name, data, *, kind="value", tags=(), facets=None, description="", caveats="",
supersedes=None, provenance=None) -> Asset`, `value(name_or_id) -> Any | None`,
`annotate(asset_id, *, caveats=None, facets=None) -> Asset`. All existing library tests
(`test_library_store*.py`, `test_library_catalog*.py`) must stay green.

## What to implement

### `put_value(name, data, ...)`
Like `put`, but the source is JSON `data`, not a file:
- Encode `data` canonically: `json.dumps(data, sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`; the id is the sha256 of that encoding's UTF-8 bytes (so `{"x":1,"y":2}` and
  `{"y":2,"x":1}` share an id). Write that exact canonical text as the blob at `items/<id>` (atomic).
- Everything else matches `put`: validate/normalise facets, write the authoritative sidecar with
  `kind` (default "value"), maintain the catalogue + novelty (`_index_new_asset`), set the alias,
  first-writer-wins on re-put, and apply supersession (below). Reuse the shared write path where you
  can rather than duplicating `put`'s body — a private helper that both `put` (with a file digest +
  copy) and `put_value` (with a JSON digest + text write) call is ideal, but keep both public
  signatures exactly as frozen.

### `value(name_or_id)`
Resolve to an id; if it resolves and the sidecar's `kind == "value"`, read the blob, `json.loads`
it, and return the parsed value. Return None when it does not resolve, the sidecar is missing, or the
asset is not a value asset (e.g. a file asset). Tolerate a malformed blob by returning None (do not
raise on a normal read).

### `annotate(asset_id, *, caveats=None, facets=None)`
- Load the existing asset via `get(asset_id)`; if None, raise `LibraryError` ("unknown asset").
- Build the updated descriptor: same `id`, `kind`, `created_utc`, `supersedes`, `tags`, `description`,
  `provenance`, `status`, and blob (content unchanged). If `caveats` is not None, replace caveats.
  If `facets` is given, validate+normalise them (declared keys only, via `_normalise_facets`) and
  MERGE into the existing facets (new keys added, existing keys overwritten).
- Rewrite the sidecar atomically (same id) and refresh the catalogue entry for this id (so `find()`
  reflects the new facets). Do NOT recompute or clear novelty for OTHER assets; for this asset, keep
  it simple — re-run the same incremental indexing used on put so the entry's fields are current.
- Return the updated `Asset`.

### Supersession on `put` / `put_value`
After the new asset's sidecar + catalogue entry are written, if `supersedes` is a non-None id that
resolves to a stored asset (its sidecar exists), flip that asset: rewrite its sidecar with
`status="superseded"` (all other fields unchanged) and refresh its catalogue entry. A `supersedes`
id that does not resolve is tolerated (recorded on the new asset; nothing to flip; no error). Do this
on both `put` and `put_value`. A re-put of identical content (first-writer-wins) should still apply a
supersession flip if `supersedes` is given.

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature; keep all existing library tests green.
- Do NOT add `ctx.library`, the `library` event, describe(), the dry-run overlay, or supervisor
  wiring — those are D-3b. No "rejected" status API here (deferred). No deletion.
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the SDK style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_library_mutations.py tests/sdk/test_library_store.py tests/sdk/test_library_store_hardening.py tests/sdk/test_library_catalog.py tests/sdk/test_library_catalog_hardening.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
