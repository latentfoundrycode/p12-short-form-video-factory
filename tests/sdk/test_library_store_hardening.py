"""D-1 review hardening: two gaps the decorrelated review surfaced.

1. Re-putting identical content must NOT overwrite the existing descriptor (§7.7: an asset is never
   replaced in place) — the accumulated caveats/provenance are exactly what must survive; only the
   name alias is (re)pointed.
2. `created_utc` must be UTC-normalised even if an aware non-UTC clock is injected.

These lock review findings; they are not part of the frozen D-1 contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sfvf.library import FacetSpec, LibraryStore

_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_reput_identical_content_keeps_the_original_descriptor(tmp_path: Path) -> None:
    store = LibraryStore(tmp_path / "lib", facets=[FacetSpec("subject")], now=lambda: _NOW)
    first = store.put(
        "bertie",
        _file(tmp_path, "1.png", b"SAME"),
        kind="image",
        description="original",
        caveats="left hand malformed",
        facets={"subject": "bertie"},
    )
    # Re-put the SAME bytes under a different name with different metadata.
    second = store.put(
        "bertie-alt",
        _file(tmp_path, "2.png", b"SAME"),
        kind="image",
        description="CLOBBER",
        caveats="",
    )
    assert second.id == first.id
    # First-writer-wins on the descriptor: the accumulated metadata is not destroyed.
    assert second.description == "original"
    assert second.caveats == "left hand malformed"
    assert second.facets == {"subject": "bertie"}
    assert store.get(first.id).description == "original"
    # Both names resolve to the one id (the alias is still (re)pointed).
    assert store.resolve("bertie") == first.id
    assert store.resolve("bertie-alt") == first.id


def test_created_utc_is_normalised_to_utc(tmp_path: Path) -> None:
    plus_two = timezone(timedelta(hours=2))
    store = LibraryStore(
        tmp_path / "lib", now=lambda: datetime(2026, 1, 2, 5, 4, 5, tzinfo=plus_two)
    )
    asset = store.put("x", _file(tmp_path, "x.bin", b"Z"), kind="file")
    assert asset.created_utc == "2026-01-02T03:04:05Z"  # 05:04+02:00 → 03:04Z
