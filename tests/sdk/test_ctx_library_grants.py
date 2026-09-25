"""TASK-SSN-A4 contract: ctx.library reads its own namespace UNION the granted owner pool.

A workflow's `ctx.library` sees its OWN namespace assets plus owner-pool assets granted to it
(by the owner via the Library tab: `{"all": true}` or `{"workflows": [ids]}`). The owner pool is
a SECOND read-only root (`paths.library_owner_pool`, `library/_owner`); writes (`put`) go only to
the workflow's own namespace. `find`/`get`/`path` merge the two with own-namespace precedence and
the grant filter for `ctx.workflow_id`. `path(name_or_id)` returns the on-disk blob path of a
resolvable, granted asset (None otherwise) — the read used to hand a music/voice file to the mixer.

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/context.py (the
facade + the new ContextPaths field).
"""

from __future__ import annotations

from pathlib import Path

from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.grants import GrantStore
from sfvf.library import LibraryStore


def _ctx(tmp_path: Path, workflow_id: str) -> Context:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
            workflow_id=workflow_id,
            workflow_version="1.0.0",
            library_facets=[],
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
                library=tmp_path / "lib",
                library_owner_pool=tmp_path / "_owner",
                library_overlay=None,
            ),
        )
    )


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _seed_owner(tmp_path: Path, name: str, content: bytes, grant: dict) -> str:
    owner = tmp_path / "_owner"
    asset = LibraryStore(owner).put(name, _file(tmp_path, name, content), kind="music")
    GrantStore(owner).set_grant(asset.id, grant)
    return asset.id


def _seed_own(tmp_path: Path, name: str, content: bytes):
    return LibraryStore(tmp_path / "lib").put(name, _file(tmp_path, name, content), kind="music")


def test_find_merges_own_and_granted_owner_pool(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "wf-me")
    own = _seed_own(tmp_path, "own.mp3", b"OWN")
    all_id = _seed_owner(tmp_path, "shared-all.mp3", b"ALL", {"all": True})
    me_id = _seed_owner(tmp_path, "shared-me.mp3", b"ME", {"workflows": ["wf-me"]})
    other_id = _seed_owner(tmp_path, "shared-other.mp3", b"OTHER", {"workflows": ["wf-other"]})
    seen = {a.id for a in ctx.library.find()}
    assert own.id in seen
    assert all_id in seen
    assert me_id in seen
    assert other_id not in seen  # granted to another workflow only


def test_get_respects_grants(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "wf-me")
    all_id = _seed_owner(tmp_path, "a.mp3", b"A", {"all": True})
    other_id = _seed_owner(tmp_path, "b.mp3", b"B", {"workflows": ["wf-other"]})
    assert ctx.library.get(all_id) is not None
    assert ctx.library.get(other_id) is None  # not granted to wf-me


def test_path_is_grant_aware_two_root(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "wf-me")
    own = LibraryStore(tmp_path / "lib").put("own", _file(tmp_path, "o.mp3", b"OWN"), kind="music")
    all_id = _seed_owner(tmp_path, "c.mp3", b"CCC", {"all": True})
    other_id = _seed_owner(tmp_path, "d.mp3", b"DDD", {"workflows": ["wf-other"]})
    assert ctx.library.path(own.id).read_bytes() == b"OWN"          # own namespace
    assert ctx.library.path(all_id).read_bytes() == b"CCC"          # granted owner-pool blob
    assert ctx.library.path(other_id) is None                       # ungranted -> no path


def test_put_writes_to_own_namespace_not_owner_pool(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "wf-me")
    asset = ctx.library.put("mine", _file(tmp_path, "m.mp3", b"MINE"), kind="music")
    # It landed in the workflow's own namespace...
    assert LibraryStore(tmp_path / "lib").get(asset.id) is not None
    # ...and NOT in the read-only owner pool.
    assert LibraryStore(tmp_path / "_owner").get(asset.id) is None


def test_own_namespace_wins_on_id_collision(tmp_path: Path) -> None:
    # Same content in both roots (same sha id); the workflow's own namespace takes precedence.
    ctx = _ctx(tmp_path, "wf-me")
    own = _seed_own(tmp_path, "dup.mp3", b"DUP")
    owner_same = LibraryStore(tmp_path / "_owner").put(
        "dup", _file(tmp_path, "dup.mp3", b"DUP"), kind="music"
    )
    GrantStore(tmp_path / "_owner").set_grant(owner_same.id, {"all": True})
    assert own.id == owner_same.id  # identical content -> identical id
    got = ctx.library.get(own.id)
    assert got is not None
    assert got.kind == "music"


def test_ungranted_owner_asset_is_invisible_without_grant(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, "wf-me")
    owner = tmp_path / "_owner"
    ungranted = LibraryStore(owner).put("u", _file(tmp_path, "u.mp3", b"U"), kind="music")
    # no grant set at all -> default deny
    assert ctx.library.get(ungranted.id) is None
    assert ungranted.id not in {a.id for a in ctx.library.find()}
