"""D-2 review hardening: crash-recovery robustness the decorrelated review surfaced.

1. A structurally-corrupt catalog.json (e.g. `{}`) must trigger a rebuild, not be trusted as an
   empty index — otherwise find() returns nothing while authoritative sidecars exist (false
   negatives that cost real money in regeneration).
2. A single corrupt/unreadable sidecar must not abort the rescan — it is quarantined (blob kept),
   and the good assets still index (§5.10 recovery by inspection).
3. Re-putting content whose sidecar exists but was never indexed (a crash between the sidecar and
   catalogue writes) self-heals via a rescan, so the asset becomes visible to find().
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf.library import FacetSpec, LibraryStore

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _store(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets, now=lambda: _NOW)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize("bad", ["{}", "{ not json", "[]", '{"quarantined": []}'])
def test_corrupt_catalog_triggers_rebuild(tmp_path: Path, bad: str) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    asset = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    # Corrupt/truncate the derived index; find() must rebuild from the authoritative sidecars.
    (tmp_path / "lib" / "catalog.json").write_text(bad, encoding="utf-8")
    assert [x.id for x in store.find(facets={"subject": "bertie"})] == [asset.id]


def test_corrupt_sidecar_does_not_abort_the_rescan(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    good = store.put("good", _file(tmp_path, "g", b"GOOD"), facets={"subject": "bertie"})
    # A blob + an unreadable sidecar (valid-looking id) sit alongside the good asset.
    corrupt_id = "f" * 64
    items = tmp_path / "lib" / "items"
    (items / corrupt_id).write_bytes(b"PAID-BLOB")
    (items / f"{corrupt_id}.json").write_text("{ not json", encoding="utf-8")
    report = store.rebuild_catalog()  # must not raise
    assert corrupt_id in report.quarantined
    assert (items / corrupt_id).is_file()  # the paid blob is kept
    assert [x.id for x in store.find(facets={"subject": "bertie"})] == [
        good.id
    ]  # good still indexed


def test_reput_reindexes_a_crash_orphaned_asset(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    # Simulate a crash after the sidecar write but before indexing: blob + sidecar on disk, but the
    # catalogue never learned about it. (Write them directly, no catalogue entry.)
    src = _file(tmp_path, "orphan", b"ORPHAN")
    store_root = tmp_path / "lib"
    (store_root / "items").mkdir(parents=True, exist_ok=True)
    asset_id = hashlib.sha256(b"ORPHAN").hexdigest()
    (store_root / "items" / asset_id).write_bytes(b"ORPHAN")
    (store_root / "items" / f"{asset_id}.json").write_text(
        json.dumps(
            {
                "id": asset_id,
                "kind": "image",
                "created_utc": "2026-01-01T00:00:00Z",
                "status": "active",
                "supersedes": None,
                "tags": [],
                "facets": {"subject": "bertie"},
                "description": "",
                "caveats": "",
                "provenance": {},
            }
        ),
        encoding="utf-8",
    )
    # No catalogue exists yet; a re-put of the identical content must self-heal the index.
    store.put("orphan", src, kind="image", facets={"subject": "bertie"})
    assert [x.id for x in store.find(facets={"subject": "bertie"})] == [asset_id]
