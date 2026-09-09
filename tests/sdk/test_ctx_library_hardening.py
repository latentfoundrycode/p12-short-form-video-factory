"""D-3b review hardening: overlay-isolation and event-protocol edges the review surfaced.

1. A dry run with no overlay must FAIL CLOSED on a write, never fall through to the real library.
2. `value()` must presence-check the overlay so a legitimately falsey stored value (0, "", [], null)
   is not mistaken for a miss and shadowed by stale real state.
3. `find()` must treat the overlay as authoritative for any id it holds, so an overlay edit can't
   let the stale real descriptor back into the result.
4. A `put` event fires on every put, but a re-put of identical content emits no fresh `novel-facet`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths, LibraryFacetDecl
from sfvf.library import FacetSpec, LibraryStore

_VERSION = "1.0.0"


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _real(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets)


def _ctx(
    tmp_path: Path,
    *,
    dry_run: bool,
    overlay: bool,
    facets: dict[str, list[str] | None] | None = None,
) -> Context:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    decls = [LibraryFacetDecl(key=k, values=v) for k, v in (facets or {}).items()]
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
                library=tmp_path / "lib",
                library_overlay=(video / ".library-overlay") if overlay else None,
            ),
            library_facets=decls,
            workflow_version=_VERSION,
        )
    )


def _library_events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [e for e in events if e.get("t") == "library"]


def test_dry_run_without_overlay_refuses_to_write(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=True, overlay=False)
    with pytest.raises(RuntimeError):
        ctx.library.put("a", _file(tmp_path, "a", b"A"))
    # Nothing reached the real library.
    assert _real(tmp_path).find(status=None) == []


def test_falsey_overlay_value_is_not_shadowed_by_real(tmp_path: Path) -> None:
    # Real holds series/state = {"episode": 5}; a dry-run overlay overwrites it with an empty list.
    real = _real(tmp_path)
    real.put_value("series/state", {"episode": 5})
    ctx = _ctx(tmp_path, dry_run=True, overlay=True)
    ctx.library.put("series/state", [])  # a legitimately falsey value in the overlay
    assert ctx.library.value("series/state") == []  # overlay wins, not the real {"episode": 5}


def test_find_overlay_is_authoritative_for_its_ids(tmp_path: Path) -> None:
    real = _real(tmp_path, FacetSpec("subject"))
    asset = real.put("bertie", _file(tmp_path, "b.png", b"PIX"), facets={"subject": "bertie"})
    ctx = _ctx(tmp_path, dry_run=True, overlay=True, facets={"subject": None, "era": None})
    # Annotate in the overlay so the asset now also carries era=post-timeskip.
    ctx.library.annotate(asset.id, facets={"era": "post-timeskip"})
    found = ctx.library.find(facets={"era": "post-timeskip"})
    assert [a.id for a in found] == [asset.id]  # the overlay version matches
    # And there is no duplicate/stale copy from real.
    assert len(ctx.library.find(facets={"subject": "bertie"})) == 1


def test_reput_identical_content_emits_no_new_novel_facet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _ctx(tmp_path, dry_run=False, overlay=False, facets={"subject": None})
    ctx.library.put("a", _file(tmp_path, "a", b"SAME"), facets={"subject": "bertie"})
    capsys.readouterr()  # drop the first put's events
    # Re-put the identical bytes: a put event fires, but the value is not newly introduced.
    ctx.library.put("a", _file(tmp_path, "a2", b"SAME"), facets={"subject": "bertie"})
    events = _library_events(capsys)
    assert [e["event"] for e in events] == ["put"]
