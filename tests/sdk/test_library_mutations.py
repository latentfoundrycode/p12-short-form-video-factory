"""D-3a contract: library value assets, annotate, and supersession (SDK §7.5-7.7).

`put_value`/`value` store and read small JSON (series state, §7.6). `annotate` updates an asset's
caveats/facets in place (same id/content, §7.5). Supersession flips the old asset's status when a
new asset names it in `supersedes` — assets are never replaced in place (§7.7); find active skips
the superseded one while the old id still resolves.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf.library import FacetSpec, LibraryError, LibraryStore

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _store(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets, now=lambda: _NOW)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# --- value assets (§7.6) ---


def test_put_value_and_read_it_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put_value("series/state", {"episode": 7, "threads": ["a"]})
    assert asset.kind == "value"
    assert store.value("series/state") == {"episode": 7, "threads": ["a"]}
    assert store.value(asset.id) == {"episode": 7, "threads": ["a"]}


def test_value_id_is_content_hash_of_canonical_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a = store.put_value("a", {"x": 1, "y": 2})
    b = store.put_value("b", {"y": 2, "x": 1})  # same data, different key order
    assert a.id == b.id  # canonical encoding → identical id


def test_value_missing_or_non_value_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.value("nope") is None
    file_asset = store.put("a-file", _file(tmp_path, "f.bin", b"RAWBYTES"), kind="file")
    assert store.value(file_asset.id) is None  # a file asset is not a value asset


def test_put_value_validates_facets(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    with pytest.raises(LibraryError):
        store.put_value("x", {"n": 1}, facets={"colour": "red"})


# --- annotate (§7.5) ---


def test_annotate_sets_caveats_without_changing_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("bertie", _file(tmp_path, "b.png", b"PIX"), kind="image")
    updated = store.annotate(asset.id, caveats="hood reads brown at small sizes")
    assert updated.id == asset.id  # content unchanged → same id
    assert updated.caveats == "hood reads brown at small sizes"
    assert store.get(asset.id).caveats == "hood reads brown at small sizes"


def test_annotate_merges_facets_and_validates(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"), FacetSpec("era"))
    asset = store.put("bertie", _file(tmp_path, "b.png", b"PIX"), facets={"subject": "bertie"})
    updated = store.annotate(asset.id, facets={"era": "Post Timeskip"})
    assert updated.facets == {"subject": "bertie", "era": "post-timeskip"}  # merged + normalised
    # The catalogue is refreshed, so find() sees the new facet.
    assert [x.id for x in store.find(facets={"era": "post-timeskip"})] == [asset.id]
    with pytest.raises(LibraryError):
        store.annotate(asset.id, facets={"colour": "red"})  # undeclared


def test_annotate_unknown_asset_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LibraryError):
        store.annotate(hashlib.sha256(b"absent").hexdigest(), caveats="x")


# --- supersession (§7.7) ---


def test_supersession_flips_the_old_asset_status(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    old = store.put("bertie", _file(tmp_path, "1.png", b"V1"), facets={"subject": "bertie"})
    new = store.put(
        "bertie", _file(tmp_path, "2.png", b"V2"), facets={"subject": "bertie"}, supersedes=old.id
    )
    assert new.status == "active"
    assert store.get(old.id).status == "superseded"  # old flipped
    active_ids = {x.id for x in store.find(facets={"subject": "bertie"}, status="active")}
    assert active_ids == {new.id}  # find(active) skips the superseded one
    assert old.id in {x.id for x in store.find(status="superseded")}
    assert store.get(old.id) is not None  # the old id still resolves forever


def test_supersedes_unknown_id_is_tolerated(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ghost = hashlib.sha256(b"ghost").hexdigest()
    asset = store.put("a", _file(tmp_path, "a.bin", b"A"), supersedes=ghost)
    assert asset.status == "active"
    assert asset.supersedes == ghost  # recorded, no crash, nothing to flip


def test_put_value_supersession(tmp_path: Path) -> None:
    store = _store(tmp_path)
    v1 = store.put_value("series/state", {"episode": 6})
    v2 = store.put_value("series/state", {"episode": 7}, supersedes=v1.id)
    assert store.get(v1.id).status == "superseded"
    assert store.value("series/state") == {"episode": 7}
    assert store.value(v2.id) == {"episode": 7}


def test_persisted_value_survives_a_fresh_instance(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put_value("series/state", {"episode": 9})
    fresh = LibraryStore(tmp_path / "lib", now=lambda: _NOW)
    assert fresh.value("series/state") == {"episode": 9}
    # And the stored blob is the canonical JSON encoding.
    asset_id = fresh.resolve("series/state")
    assert asset_id is not None
    assert json.loads((tmp_path / "lib" / "items" / asset_id).read_text(encoding="utf-8")) == {
        "episode": 9
    }
