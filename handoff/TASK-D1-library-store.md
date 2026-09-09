# TASK D-1 — content-addressed library store (SDK §7, Architecture §5.10)

## Goal (one sentence)
Implement `sfvf.library`'s content-addressed store: `put`/`get`/`resolve`/`blob_path` plus facet
declaration/normalisation, so assets are identified by content hash, named by mutable aliases, and
described by an authoritative sidecar written atomically.

## Frozen contract (already committed — do NOT edit any test)
`tests/sdk/test_library_store.py` covers: content-hash identity + blob/sidecar written; identical
content is one blob; a name is a mutable alias and an old id still resolves; clean misses; descriptor
persistence across instances; undeclared/closed-set facet rejection; open-value normalisation; the
`normalise_facet_value` cases; and no temp files left behind. Signatures in `sdk/sfvf/library.py`
(`FacetSpec`, `Asset`, `normalise_facet_value`, `LibraryError`, `LibraryStore`) are frozen.

## What to implement (fill the `raise NotImplementedError` bodies)

### `normalise_facet_value(value)`
Lowercase, `strip()`, then collapse every run of internal whitespace to a single `-`. So
`"Rain Coat"`→`"rain-coat"`, `"  a  b "`→`"a-b"`, `"SOLO"`→`"solo"`. (Use `"-".join(value.split())`
after lowercasing — `str.split()` with no args handles the trim + internal-run collapse.)

### `LibraryStore.__init__(root, *, facets, now)`
Store `root` and `now`. Build a lookup from the declared `facets`: `key -> FacetSpec`. For a closed
spec, keep its allowed set as the NORMALISED values (apply `normalise_facet_value` to each declared
value) so membership checks are consistent with how open values are normalised. `items/` is
`root/"items"`; aliases live in `root/"aliases.json"`.

### `LibraryStore.put(name, source, *, kind, tags, facets, description, caveats, supersedes, provenance)`
1. Read `source` bytes and compute `id = sha256(bytes).hexdigest()`.
2. **Validate/normalise facets** (the given `facets` mapping, default `{}`): for each `key, value` —
   reject with `LibraryError` if `key` is not declared; normalise `value` with
   `normalise_facet_value`; for a closed key, reject with `LibraryError` if the normalised value is
   not in the declared normalised set. Build the stored `facets` dict from the normalised values.
3. **Write the blob first**, then the sidecar — both atomically (temp file in the same dir, then
   `os.replace`), mirroring `sdk/sfvf/cache.py`'s `_copy_atomic` / `_write_json_atomic` (you may
   import and reuse those, or replicate the pattern). The blob is `items/<id>`; skip the copy if it
   already exists (identical content is stored once). The sidecar is `items/<id>.json` holding the
   descriptor dict: `{id, kind, created_utc, status, supersedes, tags, facets, description, caveats,
   provenance}` with `status="active"`, `created_utc` = `now()` formatted as ISO-8601 UTC `...Z`
   (e.g. `2026-01-02T03:04:05Z` — format the aware datetime, replacing `+00:00` with `Z`), `tags` a
   list, `provenance` the given mapping or `{}`.
4. If `name` is not None, set the alias `name -> id` in `aliases.json` (atomic read-modify-write:
   load the current map (or `{}`), set the key, write it back atomically). A later `put` under the
   same name repoints it.
5. Return the `Asset` (tags as a tuple, facets as the normalised dict).

### `LibraryStore.resolve(name_or_id)`
Load `aliases.json` (or `{}`). If `name_or_id` is a key there, return its id. Else if it looks like a
sha256 (64 lowercase hex chars) AND `items/<name_or_id>.json` exists, return it. Else None.

### `LibraryStore.get(name_or_id)`
`resolve` it; if None return None. Read `items/<id>.json`; if missing return None; parse and return an
`Asset` (coerce `tags` to a tuple, tolerate a missing optional field with sensible defaults —
`supersedes` None, `provenance` {}). Do not raise on a normal miss.

### `LibraryStore.blob_path(asset_id)`
Return `root/"items"/asset_id` (no existence requirement).

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature.
- Do NOT build the catalogue, `find()`, novelty events, rescan, `ctx` integration, supersession
  status-flips, `value()`/JSON assets, or the dry-run overlay — those are D-2/D-3.
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the SDK style
  (see `sdk/sfvf/cache.py`).

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_library_store.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
