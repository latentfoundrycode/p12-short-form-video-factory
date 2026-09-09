"""C-6 review hardening: two gaps the decorrelated review surfaced.

1. `ctx.map(paid=...)` must route parallel paid generation to the paid partition — otherwise the
   common "make N shots" path stores paid work in cheap, where it can be evicted and re-purchased.
2. When the cheap reference picture is INCOMPLETE (an entry is transiently unreadable — a Windows
   file lock — or corrupt), blob GC must be skipped, so a blob belonging to a live-but-unreadable
   entry is never collateral-deleted (silent corruption of a cached result).

These lock review findings; they are not part of the frozen C-6 contract.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sfvf.cache import StepCache, evict_cheap, step_key
from sfvf.context import Context, ContextFile, ContextPaths

_VERSION = "1.0.0"


def _make_ctx(tmp_path: Path) -> Context:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
                cache=tmp_path / "cache",
            ),
            workflow_version=_VERSION,
        )
    )


def test_map_paid_routes_items_to_the_paid_partition(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    out = ctx.map("gen", [1, 2], inputs=lambda i: {"i": i}, fn=lambda i: {"n": i}, paid=True)
    assert out == [{"n": 1}, {"n": 2}]
    root = tmp_path / "cache"
    for i in (1, 2):
        key = step_key(_VERSION, "gen", {"i": i})
        assert StepCache(root, partition="paid").get(key) == {"n": i}
        assert StepCache(root, partition="cheap").get(key) is None


def test_map_defaults_to_the_cheap_partition(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    ctx.map("render", [1], inputs=lambda i: {"i": i}, fn=lambda i: {"n": i})
    root = tmp_path / "cache"
    key = step_key(_VERSION, "render", {"i": 1})
    assert StepCache(root, partition="cheap").get(key) == {"n": 1}
    assert StepCache(root, partition="paid").get(key) is None


def _put(root: Path, key: str, content: bytes, last_used: float) -> None:
    src = root.parent / f"src-{key[:10]}.bin"
    src.write_bytes(content)
    StepCache(root, partition="cheap", now=lambda: last_used).put(key, {"k": key}, files={"b": src})


def _blob(root: Path, content: bytes) -> Path:
    return root / "cheap" / "blobs" / hashlib.sha256(content).hexdigest()


def test_an_unreadable_entry_disables_blob_gc(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    a = step_key("1", "f", {"x": 1})
    b = step_key("1", "f", {"x": 2})
    _put(root, a, b"A" * 10_000, last_used=1.0)
    _put(root, b, b"B" * 10_000, last_used=2.0)
    # A corrupt entry sits alongside: its blob references cannot be read, so GC must stay its hand.
    (root / "cheap" / "entries" / "corrupt").write_text("{ not json", encoding="utf-8")
    evict_cheap(root, max_bytes=15_000)  # over the ceiling → an entry may be evicted
    # No blob is deleted while the reference picture is incomplete — no collateral corruption.
    assert _blob(root, b"A" * 10_000).is_file()
    assert _blob(root, b"B" * 10_000).is_file()
