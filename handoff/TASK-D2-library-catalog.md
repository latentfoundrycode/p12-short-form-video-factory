# TASK D-2 — library catalogue + find() + novelty + crash-recovery rescan (§5.10, §7.4-7.5)

## Goal (one sentence)
Add the derived `catalog.json` index and implement `find()` (the free exact-match first tier of
selection), first-seen-value novelty, and a crash-recoverable `rebuild_catalog()` rescan — on top of
the D-1 content-addressed store.

## Frozen contract (already committed — do NOT edit any test)
`tests/sdk/test_library_catalog.py`. Frozen signatures in `sdk/sfvf/library.py`: `RebuildReport`
(fields `indexed:int`, `quarantined:tuple[str,...]`, `dropped:tuple[str,...]`),
`LibraryStore.find(*, tags=(), facets=None, status="active") -> list[Asset]`,
`LibraryStore.rebuild_catalog() -> RebuildReport`, `LibraryStore.novel_facets(asset_id) -> tuple[str,...]`.
The existing D-1 tests (`test_library_store.py`, `test_library_store_hardening.py`) must stay green.

## Catalogue format (internal; derived and rebuildable — you choose the exact JSON)
`catalog.json` at the namespace root. Suggested shape: one entry per indexed asset holding the fields
`find()` filters on plus novelty — e.g. `{"assets": {"<id>": {"status", "kind", "tags":[...],
"facets":{...}, "created_utc", "novel_facets":[...]}}, "quarantined": [...], "dropped": [...]}`. It is
NOT authoritative (the sidecars are); it exists so a facet query need not open every sidecar.

## What to implement

### Extend `put()` to maintain the catalogue (write order: blob → sidecar → catalogue entry, §5.10)
After the sidecar write (and before/with the alias write is fine), upsert this asset's catalogue
entry, computing `novel_facets`: for each OPEN facet key the asset carries (a key whose `FacetSpec`
has `values is None`), the key is novel iff no already-catalogued asset holds that (normalised) value
for that key. Do NOT mark closed-key values novel. A re-put of existing content (D-1 first-writer-wins)
must not change the existing entry's `novel_facets`. Keep `put`'s public signature unchanged.

### `find(*, tags, facets, status="active")`
- Load the catalogue; if `catalog.json` is absent, `rebuild_catalog()` first, then read it.
- Normalise the query's facet values with `normalise_facet_value` (so `"  Bertie "` matches stored
  `"bertie"`). Tags are matched verbatim.
- An asset matches when: (`status is None` or its status == status) AND it carries every tag in `tags`
  AND for every `key,value` in `facets` it holds exactly that normalised value (an absent facet does
  NOT match — §7.4).
- Load the matching sidecars via `get(id)` and return them as `list[Asset]`, ordered deterministically
  by `(created_utc, id)`.

### `rebuild_catalog() -> RebuildReport`
Rescan `items/` and rewrite `catalog.json` idempotently. Pair each `<id>` blob with its `<id>.json`
sidecar:
- **blob present, sidecar present** → index it (this covers the normal case and "crashed before
  indexing").
- **blob present, sidecar absent** → quarantine: add the id to `quarantined`, do NOT index it, and
  NEVER delete the blob.
- **sidecar present, blob absent** → drop: add the id to `dropped`, do NOT index it (flagged).
Recompute `novel_facets` deterministically: order indexed assets by `(created_utc, id)`; for each open
facet key, the FIRST asset to carry a given normalised value has that key in its `novel_facets`, the
rest do not. Return `RebuildReport(indexed=<count indexed>, quarantined=tuple(sorted...),
dropped=tuple(sorted...))`. Write the catalogue atomically (reuse `_write_json_atomic`).

### `novel_facets(asset_id)`
Read the catalogue (rebuild if absent); return the asset's `novel_facets` as a tuple (empty for an
unknown asset or one that introduced nothing).

## Constraints / do-nots
- Do NOT edit any test or change a frozen signature; keep the D-1 tests green.
- Do NOT emit the `library` event, add `ctx` integration, supersession status-flips, `annotate`,
  `value()`/JSON assets, or the dry-run overlay — those are D-3. (Novelty is only RECORDED here; the
  event is emitted in D-3.)
- Only open facets are novelty-tracked. Closed facets never mark novel.
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the SDK style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_library_catalog.py tests/sdk/test_library_store.py tests/sdk/test_library_store_hardening.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
