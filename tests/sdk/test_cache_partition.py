"""C-6 contract: the cache is split into paid/cheap partitions with a recency stamp (§5.9).

`paid` results (paid generation) live in their own subtree and are never auto-evicted; `cheap`
results (renders/research) live separately and carry a `last_used` stamp so LRU eviction can order
them. The two partitions are independent stores — the same key in each is a different entry.
"""

from __future__ import annotations

import json
from pathlib import Path

from sfvf.cache import StepCache, step_key


def test_paid_and_cheap_are_independent_partitions(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    key = step_key("1", "gen", {"x": 1})
    StepCache(root, partition="paid").put(key, {"v": "paid"})
    # The same key in the cheap partition is a separate slot — a miss until its own put.
    assert StepCache(root, partition="cheap").get(key) is None
    StepCache(root, partition="cheap").put(key, {"v": "cheap"})
    assert StepCache(root, partition="paid").get(key) == {"v": "paid"}
    assert StepCache(root, partition="cheap").get(key) == {"v": "cheap"}
    # Physically separate subtrees.
    assert (root / "paid" / "entries" / key).is_file()
    assert (root / "cheap" / "entries" / key).is_file()


def test_default_partition_is_cheap(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    key = step_key("1", "f", {"x": 1})
    StepCache(root).put(key, {"v": 1})
    assert StepCache(root, partition="cheap").get(key) == {"v": 1}
    assert (root / "cheap" / "entries" / key).is_file()


def test_files_round_trip_within_a_partition(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    src = tmp_path / "art" / "final.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"FRAMES")
    key = step_key("1", "gen", {"shot": 4})
    StepCache(root, partition="paid").put(key, {"video": "final.mp4"}, files={"final.mp4": src})
    restore = tmp_path / "restore"
    restore.mkdir()
    value = StepCache(root, partition="paid").get(key, restore_into=restore)
    assert value == {"video": "final.mp4"}
    assert (restore / "final.mp4").read_bytes() == b"FRAMES"


def _last_used(root: Path, partition: str, key: str) -> float:
    raw = json.loads((root / partition / "entries" / key).read_text(encoding="utf-8"))
    return float(raw["last_used"])


def test_last_used_is_set_on_put_and_refreshed_on_get(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    clock = [100.0]
    cache = StepCache(root, partition="cheap", now=lambda: clock[0])
    key = step_key("1", "f", {"x": 1})
    cache.put(key, {"v": 1})
    assert _last_used(root, "cheap", key) == 100.0
    # A cache hit refreshes recency (so a used entry is not the first to be evicted).
    clock[0] = 250.0
    assert cache.get(key) == {"v": 1}
    assert _last_used(root, "cheap", key) == 250.0
