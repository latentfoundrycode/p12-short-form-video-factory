"""TASK-SSN-A1 contract: deactivate / reactivate an asset (the Library tab's "remove" = hide).

An owner "removes" a library asset by DEACTIVATING it, never by deleting the content — assets are
content-addressed and never erased (library.py §7.7). Deactivation flips the asset's status to a new
`inactive` value (distinct from `superseded`), which the default `find` (status="active") hides;
`reactivate` restores it. Both are id-targeted metadata-only flips (id and blob unchanged), like
`annotate`; an unknown id raises LibraryError; both are idempotent.

Supervisor-authored frozen contract (RED-first): this test is written before the implementation;
the builder implements only `sdk/sfvf/library.py` to make it pass and touches no test file.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sfvf.library import LibraryError, LibraryStore

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _store(tmp_path: Path) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", now=lambda: _NOW)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_deactivate_flips_status_to_inactive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    assert asset.status == "active"
    updated = store.deactivate(asset.id)
    assert updated.status == "inactive"
    assert updated.id == asset.id  # metadata-only: id/content unchanged
    assert store.get(asset.id).status == "inactive"


def test_deactivate_hides_from_default_find_but_status_query_sees_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    store.deactivate(asset.id)
    assert [a.id for a in store.find()] == []  # default status="active" hides it
    assert [a.id for a in store.find(status="inactive")] == [asset.id]
    assert asset.id in [a.id for a in store.find(status=None)]  # status=None = any status


def test_reactivate_restores_active(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    store.deactivate(asset.id)
    restored = store.reactivate(asset.id)
    assert restored.status == "active"
    assert [a.id for a in store.find()] == [asset.id]


def test_deactivate_and_reactivate_are_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    store.deactivate(asset.id)
    assert store.deactivate(asset.id).status == "inactive"  # idempotent: stays inactive
    store.reactivate(asset.id)
    assert store.reactivate(asset.id).status == "active"  # idempotent: stays active


def test_deactivate_leaves_blob_and_content_intact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    asset = store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    store.deactivate(asset.id)
    assert store.blob_path(asset.id).read_bytes() == b"AUDIO"  # never erased


def test_deactivate_unknown_id_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LibraryError):
        store.deactivate("0" * 64)


def test_reactivate_unknown_id_raises(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(LibraryError):
        store.reactivate("0" * 64)


def test_deactivate_is_id_targeted_not_alias(tmp_path: Path) -> None:
    # Like annotate, deactivate takes an asset id, never an alias name.
    store = _store(tmp_path)
    store.put("track", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    with pytest.raises(LibraryError):
        store.deactivate("track")  # a name, not an id -> not found
