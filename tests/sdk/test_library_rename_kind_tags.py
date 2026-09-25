"""SDK contract: rename, kind change, and tag replacement on existing library assets."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sfvf.library import LibraryError, LibraryStore


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_rename_updates_alias_and_removes_old_name(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "lib")
    asset = store.put("old-name", _file(tmp_path, "a.mp3", b"AUDIO"), kind="music")
    store.rename(asset.id, "new-name")
    assert store.name_for(asset.id) == "new-name"
    assert store.resolve("new-name") == asset.id
    assert store.resolve("old-name") is None


def test_rename_unknown_asset_raises(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "lib")
    with pytest.raises(LibraryError):
        store.rename(hashlib.sha256(b"missing").hexdigest(), "x")


def test_annotate_replaces_kind_and_tags(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "lib")
    asset = store.put(
        "track",
        _file(tmp_path, "t.mp3", b"AUDIO"),
        kind="music",
        tags=("mood:calm", "energy:low", "other:tag"),
    )
    updated = store.annotate(
        asset.id,
        kind="sfx",
        tags=("mood:bright", "energy:high"),
    )
    assert updated.kind == "sfx"
    assert updated.tags == ("mood:bright", "energy:high")
