"""Reviewer-authored contract for the content-addressed step cache (SDK-1).

Covers Architecture §5.9 and Workflow SDK §5.2a/§5.3/§5.5: the key is derived from the
workflow version + step family + inputs in a canonical order, any Path in inputs is hashed
by the file's CONTENT (not its text), the label is never part of the key, and a stored
result plus its files are round-tripped, files stored/restored by content.
"""

import hashlib
from pathlib import Path

import pytest
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


def test_path_input_does_not_collide_with_a_string_of_its_digest(tmp_path: Path) -> None:
    """A Path (content-hashed) must be structurally distinct from a plain string that
    happens to equal that content digest — otherwise the two collide in the key."""
    f = tmp_path / "ref.bin"
    f.write_bytes(b"DATA")
    digest = hashlib.sha256(b"DATA").hexdigest()
    assert step_key("1", "gen", {"ref": f}) != step_key("1", "gen", {"ref": digest})


def test_path_used_as_a_dict_key_is_content_hashed_not_texted(tmp_path: Path) -> None:
    """A Path anywhere in inputs — including as a dict key — is content-hashed, so the
    same content at two different paths keys identically."""
    a = tmp_path / "a" / "k.bin"
    a.parent.mkdir()
    a.write_bytes(b"SAME")
    b = tmp_path / "b" / "k.bin"
    b.parent.mkdir()
    b.write_bytes(b"SAME")
    c = tmp_path / "c" / "k.bin"
    c.parent.mkdir()
    c.write_bytes(b"OTHER")
    assert step_key("1", "gen", {"m": {a: 1}}) == step_key("1", "gen", {"m": {b: 1}})
    assert step_key("1", "gen", {"m": {a: 1}}) != step_key("1", "gen", {"m": {c: 1}})


def test_cache_rejects_file_names_that_escape_restore_into(tmp_path: Path) -> None:
    """A stored file name must be a confined relative path; an absolute name or one with
    `..` must be refused so restore cannot write outside restore_into."""
    cache = StepCache(tmp_path / "cache")
    src = tmp_path / "src.bin"
    src.write_bytes(b"X")
    key = step_key("1", "f", {"x": 1})
    for bad in ("../escape.bin", "a/../../escape.bin"):
        with pytest.raises(ValueError):
            cache.put(key, {"v": 1}, files={bad: src})
    # An absolute name is refused too.
    absolute = str((tmp_path / "outside.bin").resolve())
    with pytest.raises(ValueError):
        cache.put(key, {"v": 1}, files={absolute: src})
    # Nothing escaped the cache root.
    assert not (tmp_path / "escape.bin").exists()
    assert not (tmp_path / "outside.bin").exists()


def test_dict_keyed_by_content_identical_paths_is_order_independent(tmp_path: Path) -> None:
    """Two distinct Path keys whose files have identical content canonicalize identically;
    the step key must not depend on their insertion order (a lexical sort tie must not
    fall back to insertion order)."""
    a = tmp_path / "a" / "k.bin"
    a.parent.mkdir()
    a.write_bytes(b"IDENTICAL")
    b = tmp_path / "b" / "k.bin"
    b.parent.mkdir()
    b.write_bytes(b"IDENTICAL")
    assert step_key("1", "gen", {a: 1, b: 2}) == step_key("1", "gen", {b: 2, a: 1})


def test_restore_refuses_to_follow_a_symlink_out_of_restore_into(tmp_path: Path) -> None:
    """A lexically-clean file name must still not escape via a pre-existing symlink under
    restore_into (resolve + containment check, mirroring the 005-3 file server)."""
    cache = StepCache(tmp_path / "cache")
    src = tmp_path / "src.bin"
    src.write_bytes(b"SECRET-BYTES")
    key = step_key("1", "f", {"x": 1})
    cache.put(key, {"v": 1}, files={"link/foo.bin": src})  # name is lexically confined

    restore = tmp_path / "restore"
    restore.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (restore / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks in this environment")

    with pytest.raises(ValueError):
        cache.get(key, restore_into=restore)
    assert not (outside / "foo.bin").exists()  # nothing written through the symlink


def test_a_dict_does_not_collide_with_a_pair_shaped_list(tmp_path: Path) -> None:
    """A dict and a list that happens to be shaped like the dict's canonical pair-list
    must key differently — the canonical form of a dict must be distinguishable from a
    plain list, closing the container-shape ambiguity class."""
    as_dict = step_key("1", "gen", {"x": {"a": 1}})
    as_pairs = step_key("1", "gen", {"x": [["a", 1]]})
    assert as_dict != as_pairs
