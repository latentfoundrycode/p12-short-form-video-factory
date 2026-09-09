"""D-1 contract: the content-addressed library store (SDK §7, Architecture §5.10).

An asset is identified by the sha256 of its contents; a name is a mutable alias pointing at an id.
The descriptor sidecar is authoritative and persists. Facet keys must be declared; closed keys
reject out-of-set values; open values are normalised so variants converge. Writes are atomic.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf.library import Asset, FacetSpec, LibraryError, LibraryStore, normalise_facet_value

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _store(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets, now=lambda: _NOW)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_put_hashes_by_content_and_stores_blob_and_sidecar(tmp_path: Path) -> None:
    store = _store(tmp_path)
    src = _file(tmp_path, "sheet.png", b"BERTIE-PIXELS")
    asset = store.put("char/bertie", src, kind="image", description="a turnaround")
    assert asset.id == hashlib.sha256(b"BERTIE-PIXELS").hexdigest()
    assert asset.kind == "image"
    assert asset.status == "active"  # default
    assert asset.created_utc == "2026-01-02T03:04:05Z"
    lib = tmp_path / "lib"
    assert (lib / "items" / asset.id).read_bytes() == b"BERTIE-PIXELS"
    assert (lib / "items" / f"{asset.id}.json").is_file()
    assert store.blob_path(asset.id) == lib / "items" / asset.id


def test_identical_content_is_one_blob(tmp_path: Path) -> None:
    store = _store(tmp_path)
    a = store.put("a", _file(tmp_path, "a.bin", b"SAME"), kind="file")
    b = store.put("b", _file(tmp_path, "b.bin", b"SAME"), kind="file")
    assert a.id == b.id
    blobs = list((tmp_path / "lib" / "items").glob("*"))
    # exactly one blob + one sidecar for the single id
    assert sorted(p.name for p in blobs) == [a.id, f"{a.id}.json"]


def test_name_is_a_mutable_alias_old_id_still_resolves(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.put("char/bertie/canonical", _file(tmp_path, "1.png", b"V1"), kind="image")
    second = store.put("char/bertie/canonical", _file(tmp_path, "2.png", b"V2"), kind="image")
    assert first.id != second.id
    assert store.get("char/bertie/canonical").id == second.id  # name now points at the new id
    assert store.resolve("char/bertie/canonical") == second.id
    assert store.get(first.id).id == first.id  # the old id still resolves forever


def test_get_and_resolve_miss_cleanly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get("nope") is None
    assert store.resolve("nope") is None
    assert store.get(hashlib.sha256(b"absent").hexdigest()) is None


def test_descriptor_persists_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    asset = store.put(
        "char/bertie",
        _file(tmp_path, "s.png", b"PIX"),
        kind="image",
        tags=["character", "turnaround"],
        facets={"subject": "bertie"},
        description="full body",
        caveats="left hand malformed",
        provenance={"run_id": "r1", "cost": {"higgsfield": 12}},
    )
    fresh = LibraryStore(tmp_path / "lib", facets=[FacetSpec("subject")], now=lambda: _NOW)
    got = fresh.get(asset.id)
    assert got is not None
    assert got.tags == ("character", "turnaround")
    assert got.facets == {"subject": "bertie"}
    assert got.description == "full body"
    assert got.caveats == "left hand malformed"
    assert got.provenance == {"run_id": "r1", "cost": {"higgsfield": 12}}
    assert isinstance(got, Asset)


def test_undeclared_facet_key_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    with pytest.raises(LibraryError):
        store.put("x", _file(tmp_path, "x.bin", b"X"), facets={"colour": "red"})


def test_closed_facet_rejects_out_of_set_value(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("outfit", ("raincoat", "suit")))
    ok = store.put("y", _file(tmp_path, "y.bin", b"Y"), facets={"outfit": "raincoat"})
    assert ok.facets == {"outfit": "raincoat"}
    with pytest.raises(LibraryError):
        store.put("z", _file(tmp_path, "z.bin", b"Z"), facets={"outfit": "tuxedo"})


def test_open_facet_value_is_normalised(tmp_path: Path) -> None:
    store = _store(tmp_path, FacetSpec("subject"))
    asset = store.put("w", _file(tmp_path, "w.bin", b"W"), facets={"subject": "  Bertie  Prime "})
    assert asset.facets == {"subject": "bertie-prime"}


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("Rain Coat", "rain-coat"),
        ("  a  b ", "a-b"),
        ("SOLO", "solo"),
        ("post timeskip", "post-timeskip"),
    ],
)
def test_normalise_facet_value(raw: str, want: str) -> None:
    assert normalise_facet_value(raw) == want


def test_writes_leave_no_temporary_files(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.put("a", _file(tmp_path, "a.bin", b"AAA"), kind="file")
    names = [p.name for p in (tmp_path / "lib" / "items").iterdir()]
    assert all(not n.endswith(".tmp") and not n.startswith(".") for n in names)
