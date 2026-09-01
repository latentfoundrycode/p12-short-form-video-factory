"""Reviewer-authored contract for the content-addressed step cache (SDK-1).

Covers Architecture §5.9 and Workflow SDK §5.2a/§5.3/§5.5: the key is derived from the
workflow version + step family + inputs in a canonical order, any Path in inputs is hashed
by the file's CONTENT (not its text), the label is never part of the key, and a stored
result plus its files are round-tripped, files stored/restored by content.
"""

from pathlib import Path

from sfvf.cache import StepCache, step_key


def test_step_key_is_sha256_hex_and_order_independent() -> None:
    k1 = step_key("1.0.0", "write-script", {"topic": "a", "duration": 5})
    k2 = step_key("1.0.0", "write-script", {"duration": 5, "topic": "a"})
    assert k1 == k2  # canonical: input key order must not matter
    assert isinstance(k1, str)
    assert len(k1) == 64  # SHA-256 hex
    assert all(c in "0123456789abcdef" for c in k1)


def test_step_key_changes_with_version_family_and_input_value() -> None:
    base = step_key("1.0.0", "f", {"x": 1})
    assert step_key("1.0.1", "f", {"x": 1}) != base  # version bump invalidates
    assert step_key("1.0.0", "g", {"x": 1}) != base  # different family
    assert step_key("1.0.0", "f", {"x": 2}) != base  # different input value
    assert step_key("1.0.0", "f", {"x": 1, "y": 0}) != base  # extra input


def test_path_input_is_hashed_by_content_not_text(tmp_path: Path) -> None:
    a = tmp_path / "a" / "ref.mp4"
    a.parent.mkdir()
    a.write_bytes(b"VIDEO-CONTENT")
    b = tmp_path / "b" / "ref.mp4"
    b.parent.mkdir()
    b.write_bytes(b"VIDEO-CONTENT")  # same content, different path
    c = tmp_path / "c" / "ref.mp4"
    c.parent.mkdir()
    c.write_bytes(b"DIFFERENT")  # different content, same file name

    # Same content at different paths -> same key (the path text must not leak in).
    assert step_key("1", "gen", {"ref": a}) == step_key("1", "gen", {"ref": b})
    # Different content -> different key, even at an identically-named path.
    assert step_key("1", "gen", {"ref": a}) != step_key("1", "gen", {"ref": c})
    # A Path nested inside a structure is still content-hashed.
    assert step_key("1", "gen", {"refs": [a]}) == step_key("1", "gen", {"refs": [b]})
    assert step_key("1", "gen", {"refs": [a]}) != step_key("1", "gen", {"refs": [c]})


def test_cache_roundtrips_a_value_and_misses_cleanly(tmp_path: Path) -> None:
    cache = StepCache(tmp_path / "cache")
    key = step_key("1", "write-script", {"topic": "x"})
    assert cache.get(key) is None  # miss before any put
    cache.put(key, {"script": "hello", "words": 3})
    assert cache.get(key) == {"script": "hello", "words": 3}
    # An unrelated key still misses.
    assert cache.get(step_key("1", "write-script", {"topic": "y"})) is None


def test_cache_stores_and_restores_files_by_content(tmp_path: Path) -> None:
    cache = StepCache(tmp_path / "cache")
    src = tmp_path / "artifacts" / "final.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"FRAMES")
    nested = tmp_path / "artifacts" / "sheets" / "bertie.png"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"PNGDATA")

    key = step_key("1", "generate-shot", {"shot": 4})
    cache.put(
        key,
        {"video": "final.mp4", "sheet": "sheets/bertie.png"},
        files={"final.mp4": src, "sheets/bertie.png": nested},
    )

    restore = tmp_path / "restore"
    restore.mkdir()
    value = cache.get(key, restore_into=restore)
    assert value == {"video": "final.mp4", "sheet": "sheets/bertie.png"}
    assert (restore / "final.mp4").read_bytes() == b"FRAMES"
    assert (restore / "sheets" / "bertie.png").read_bytes() == b"PNGDATA"


def test_cache_survives_a_fresh_instance_on_the_same_root(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    key = step_key("1", "f", {"x": 1})
    StepCache(root).put(key, {"ok": True})
    # A new process/instance pointed at the same root must see the stored result.
    assert StepCache(root).get(key) == {"ok": True}
