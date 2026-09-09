"""D-3a review hardening: three mutation edges the decorrelated review surfaced.

1. An asset must never supersede itself (a re-put naming its own id would flip the sole asset to
   'superseded' while the returned descriptor still read 'active').
2. Id-targeted operations (annotate, supersession) resolve the id DIRECTLY, never via an alias — a
   pathological alias whose name equals another asset's id cannot redirect the mutation.
3. Annotating an asset's caveats must not erase its novelty marker (nor anyone else's), and stays
   consistent with a catalogue rebuild.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
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


def test_an_asset_cannot_supersede_itself(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    content = b"SELF"
    asset_id = hashlib.sha256(content).hexdigest()
    asset = store.put(
        "a", _file(tmp_path, "a", content), facets={"subject": "x"}, supersedes=asset_id
    )
    assert asset.status == "active"
    assert store.get(asset_id).status == "active"  # not flipped to superseded
    assert [x.id for x in store.find(status="active")] == [asset_id]  # still active/findable


def test_annotate_targets_the_id_not_a_colliding_alias(tmp_path: Path) -> None:
    store = _store(tmp_path)
    real = store.put("y-name", _file(tmp_path, "y", b"YYY"), kind="image")  # the asset we annotate
    other = store.put("x-name", _file(tmp_path, "x", b"XXX"), kind="image")
    # Pathological: an alias whose NAME is exactly `real`'s id, pointing at `other`.
    store.put(
        real.id, _file(tmp_path, "x2", b"XXX"), kind="image"
    )  # sets alias real.id -> other.id
    store.annotate(real.id, caveats="belongs to Y")
    # The real asset (by id) was annotated, not the alias target.
    y_sidecar = json.loads((tmp_path / "lib" / "items" / f"{real.id}.json").read_text())
    assert y_sidecar["caveats"] == "belongs to Y"
    assert store.get("x-name").caveats == ""  # the alias target was untouched
    assert other.id != real.id


def test_annotating_caveats_preserves_novelty(tmp_path: Path) -> None:
    # Increasing clock so the first asset is unambiguously earliest by created_utc.
    ticks = iter(_NOW + timedelta(minutes=i) for i in range(10))
    store = LibraryStore(tmp_path / "lib", facets=[FacetSpec("subject")], now=lambda: next(ticks))
    first = store.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    second = store.put("b", _file(tmp_path, "b", b"B"), facets={"subject": "bertie"})
    assert store.novel_facets(first.id) == ("subject",)
    assert store.novel_facets(second.id) == ()
    # Annotating the FIRST asset's caveats must not hand its novelty marker to the second.
    store.annotate(first.id, caveats="note added after use")
    assert store.novel_facets(first.id) == ("subject",)
    assert store.novel_facets(second.id) == ()
    # And a rebuild agrees (annotate stayed consistent with the deterministic recompute).
    store.rebuild_catalog()
    assert store.novel_facets(first.id) == ("subject",)
    assert store.novel_facets(second.id) == ()
