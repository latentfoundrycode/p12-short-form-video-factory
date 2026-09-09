"""C-6 contract: LRU eviction of the cheap cache partition (Architecture §5.9).

`cache/cheap` is deleted least-recently-used first once its total size exceeds a configured limit;
`cache/paid` is never touched. Files (content-addressed blobs) are deleted only when no surviving
cheap entry still references them, so a blob shared by a surviving entry is kept.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sfvf.cache import StepCache, evict_cheap, step_key


def _put(
    root: Path, partition: str, key: str, value: object, *, content: bytes | None, last_used: float
) -> None:
    files = None
    if content is not None:
        src = root.parent / f"src-{key[:10]}-{partition}.bin"
        src.write_bytes(content)
        files = {"blob.bin": src}
    StepCache(root, partition=partition, now=lambda: last_used).put(key, value, files=files)


def _blob(root: Path, partition: str, content: bytes) -> Path:
    return root / partition / "blobs" / hashlib.sha256(content).hexdigest()


def test_evict_is_noop_when_within_max(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    key = step_key("1", "f", {"x": 1})
    _put(root, "cheap", key, {"v": 1}, content=b"X" * 1000, last_used=1.0)
    assert evict_cheap(root, max_bytes=10_000_000) == 0
    assert StepCache(root, partition="cheap").get(key) == {"v": 1}
    assert _blob(root, "cheap", b"X" * 1000).is_file()


def test_evicts_least_recently_used_first(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    keys: list[str] = []
    for i, used in ((1, 1.0), (2, 2.0), (3, 3.0)):
        key = step_key("1", "f", {"x": i})
        keys.append(key)
        _put(root, "cheap", key, {"v": i}, content=bytes([65 + i]) * 10_000, last_used=used)
    # Each entry is a ~10 KB blob plus a tiny entry file; a 15 KB ceiling leaves room for one.
    assert evict_cheap(root, max_bytes=15_000) == 2
    assert StepCache(root, partition="cheap").get(keys[0]) is None  # oldest evicted
    assert StepCache(root, partition="cheap").get(keys[1]) is None
    assert StepCache(root, partition="cheap").get(keys[2]) == {"v": 3}  # newest kept


def test_get_refreshes_recency_so_a_used_entry_survives(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    old = step_key("1", "f", {"x": 1})
    new = step_key("1", "f", {"x": 2})
    _put(root, "cheap", old, {"v": 1}, content=b"A" * 10_000, last_used=1.0)
    _put(root, "cheap", new, {"v": 2}, content=b"B" * 10_000, last_used=2.0)
    # Touch the older entry at t=9 so it becomes the most recently used.
    assert StepCache(root, partition="cheap", now=lambda: 9.0).get(old) == {"v": 1}
    assert evict_cheap(root, max_bytes=15_000) == 1
    assert StepCache(root, partition="cheap").get(old) == {"v": 1}  # refreshed → survives
    assert StepCache(root, partition="cheap").get(new) is None  # now the least recently used


def test_paid_partition_is_never_evicted(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    paid = step_key("1", "p", {"x": 1})
    cheap = step_key("1", "c", {"x": 1})
    _put(root, "paid", paid, {"v": "paid"}, content=b"P" * 10_000, last_used=1.0)
    _put(root, "cheap", cheap, {"v": "cheap"}, content=b"C" * 10_000, last_used=1.0)
    evict_cheap(root, max_bytes=1)  # force out everything evictable
    assert StepCache(root, partition="paid").get(paid) == {"v": "paid"}
    assert _blob(root, "paid", b"P" * 10_000).is_file()
    assert StepCache(root, partition="cheap").get(cheap) is None


def test_unreferenced_blob_deleted_but_shared_blob_survives(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    lone = b"L" * 12_000
    shared = b"S" * 12_000
    k_old = step_key("1", "f", {"x": 1})
    k_mid = step_key("1", "f", {"x": 2})
    k_new = step_key("1", "f", {"x": 3})
    _put(root, "cheap", k_old, {"v": 1}, content=lone, last_used=1.0)  # oldest, its own blob
    _put(root, "cheap", k_mid, {"v": 2}, content=shared, last_used=2.0)  # shares a blob with k_new
    _put(root, "cheap", k_new, {"v": 3}, content=shared, last_used=3.0)  # same content → same blob
    # Dropping the oldest alone (freeing the lone 12 KB blob) brings the total under the ceiling.
    assert evict_cheap(root, max_bytes=15_000) == 1
    assert StepCache(root, partition="cheap").get(k_old) is None
    assert not _blob(root, "cheap", lone).is_file()  # unreferenced → deleted
    assert _blob(root, "cheap", shared).is_file()  # still referenced by k_mid/k_new → kept
    assert StepCache(root, partition="cheap").get(k_mid) == {"v": 2}
    assert StepCache(root, partition="cheap").get(k_new) == {"v": 3}
