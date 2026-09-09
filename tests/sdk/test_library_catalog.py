"""D-2 contract: the library catalogue, find(), novelty, and crash-recovery rescan (§5.10, §7.4-5).

`find()` is the free, deterministic first tier of selection: exact tag/facet/status matching read
from the derived `catalog.json` (rebuilt from `items/` when absent). Novelty surfaces a first-seen
facet value. A rescan is crash-recoverable by inspection: a blob with no sidecar is quarantined and
never deleted; a sidecar with no blob is dropped from the index.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sfvf.library import FacetSpec, LibraryStore

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _store(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets, now=lambda: _NOW)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _seed_raw(
    tmp_path: Path,
    content: bytes,
    *,
    status: str = "active",
    facets: dict[str, str] | None = None,
    tags: list[str] | None = None,
    created_utc: str = "2026-01-01T00:00:00Z",
    with_blob: bool = True,
    with_sidecar: bool = True,
) -> str:
    """Write a raw blob and/or sidecar directly, bypassing put() — for status and crash states."""
    asset_id = hashlib.sha256(content).hexdigest()
    items = tmp_path / "lib" / "items"
    items.mkdir(parents=True, exist_ok=True)
    if with_blob:
        (items / asset_id).write_bytes(content)
    if with_sidecar:
        (items / f"{asset_id}.json").write_text(
            json.dumps(
                {
                    "id": asset_id,
                    "kind": "file",
                    "created_utc": created_utc,
                    "status": status,
                    "supersedes": None,
                    "tags": tags or [],
                    "facets": facets or {},
                    "description": "",
                    "caveats": "",
                    "provenance": {},
                }
            ),
            encoding="utf-8",
        )
    return asset_id


def test_find_by_facet_exact_match(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    a = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    store.put("b", _file(tmp_path, "b", b"B"), facets={"subject": "wilhelmina"})
    found = store.find(facets={"subject": "bertie"})
    assert [x.id for x in found] == [a.id]


def test_find_normalises_query_facet_values(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    a = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    assert [x.id for x in store.find(facets={"subject": "  Bertie "})] == [a.id]


def test_find_requires_all_facets_and_tags(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"), FacetSpec("outfit"))
    a = store.put(
        "a",
        _file(tmp_path, "a", b"A"),
        tags=["character"],
        facets={"subject": "bertie", "outfit": "raincoat"},
    )
    store.put("b", _file(tmp_path, "b", b"B"), tags=["prop"], facets={"subject": "bertie"})
    assert [x.id for x in store.find(facets={"subject": "bertie", "outfit": "raincoat"})] == [a.id]
    assert [x.id for x in store.find(tags=["character"])] == [a.id]
    # An absent facet never matches a query for it.
    assert store.find(facets={"subject": "bertie", "outfit": "suit"}) == []


def test_status_filter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    active = store.put("a", _file(tmp_path, "a", b"A"))
    rejected = _seed_raw(tmp_path, b"REJECTED", status="rejected")
    store.rebuild_catalog()
    assert [x.id for x in store.find(status="active")] == [active.id]
    assert [x.id for x in store.find(status="rejected")] == [rejected]
    ids = {x.id for x in store.find(status=None)}
    assert ids == {active.id, rejected}


def test_catalog_rebuilds_when_absent(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    a = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    (tmp_path / "lib" / "catalog.json").unlink(missing_ok=True)  # doubt the index
    assert [x.id for x in store.find(facets={"subject": "bertie"})] == [a.id]  # rebuilt from items/


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    first = store.rebuild_catalog()
    second = store.rebuild_catalog()
    assert first.indexed == second.indexed == 1
    assert second.quarantined == () and second.dropped == ()


def test_blob_without_sidecar_is_quarantined_never_deleted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    orphan = _seed_raw(tmp_path, b"ORPHAN-BLOB", with_sidecar=False)
    report = store.rebuild_catalog()
    assert orphan in report.quarantined
    assert store.find(status=None) == []  # not indexed
    assert (tmp_path / "lib" / "items" / orphan).is_file()  # blob kept — it cost money


def test_sidecar_without_blob_is_dropped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ghost = _seed_raw(tmp_path, b"GHOST", with_blob=False)
    report = store.rebuild_catalog()
    assert ghost in report.dropped
    assert store.find(status=None) == []


def test_novelty_marks_first_seen_open_value(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    first = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    same = store.put("b", _file(tmp_path, "b", b"B"), facets={"subject": "bertie"})
    fresh = store.put("c", _file(tmp_path, "c", b"C"), facets={"subject": "wilhelmina"})
    assert store.novel_facets(first.id) == ("subject",)  # introduced "bertie"
    assert store.novel_facets(same.id) == ()  # value already seen
    assert store.novel_facets(fresh.id) == ("subject",)  # introduced "wilhelmina"


def test_novelty_survives_a_rebuild(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    first = _seed_raw(
        tmp_path, b"A", facets={"subject": "bertie"}, created_utc="2026-01-01T00:00:00Z"
    )
    later = _seed_raw(
        tmp_path, b"B", facets={"subject": "bertie"}, created_utc="2026-01-02T00:00:00Z"
    )
    store.rebuild_catalog()
    assert store.novel_facets(first) == ("subject",)  # earliest by created_utc introduced it
    assert store.novel_facets(later) == ()
