"""D-3b contract: the `ctx.library` runtime facade + novelty event + dry-run overlay (SDK §7).

Reads resolve against the real library; writes go to the real library in a real run and to a
discarded per-run OVERLAY in a dry run, so a dry run rehearses "find seven, generate the missing
one, use all eight" without mutating the real library (§7.9). `put` takes a file or JSON; a novel
first-seen open facet value emits a `library` event; `describe` hands the agent text, not a choice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths, LibraryFacetDecl
from sfvf.library import FacetSpec, LibraryStore

_VERSION = "1.0.0"


def _ctx(
    tmp_path: Path, *, dry_run: bool = False, facets: dict[str, list[str] | None] | None = None
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
                library_overlay=(video / ".library-overlay") if dry_run else None,
            ),
            library_facets=decls,
            workflow_version=_VERSION,
        )
    )


def _real(tmp_path: Path, *facets: FacetSpec) -> LibraryStore:
    return LibraryStore(tmp_path / "lib", facets=facets)


def _file(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _library_events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [e for e in events if e.get("t") == "library"]


def test_real_run_put_file_reaches_the_real_library(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, facets={"subject": None})
    asset = ctx.library.put(
        "bertie", _file(tmp_path, "b.png", b"PIX"), facets={"subject": "bertie"}
    )
    assert asset.kind == "file"
    assert ctx.library.get("bertie").id == asset.id
    assert [a.id for a in ctx.library.find(facets={"subject": "bertie"})] == [asset.id]
    # It really landed in the real library (a fresh store on the same root sees it).
    assert _real(tmp_path).get(asset.id) is not None


def test_put_json_is_a_value_asset(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    asset = ctx.library.put("series/state", {"episode": 7})
    assert asset.kind == "value"
    assert ctx.library.value("series/state") == {"episode": 7}


def test_describe_returns_text_mentioning_the_assets(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, facets={"subject": None})
    ctx.library.put(
        "bertie",
        _file(tmp_path, "b.png", b"PIX"),
        facets={"subject": "bertie"},
        description="full-body turnaround",
    )
    text = ctx.library.describe(ctx.library.find(facets={"subject": "bertie"}))
    assert isinstance(text, str)
    assert "full-body turnaround" in text
    assert "bertie" in text


def test_novel_open_value_emits_a_library_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _ctx(tmp_path, facets={"subject": None})
    ctx.library.put("a", _file(tmp_path, "a", b"A"), facets={"subject": "bertie"})
    events = _library_events(capsys)
    assert len(events) == 1
    # A reused value does not emit again.
    ctx.library.put("b", _file(tmp_path, "b", b"B"), facets={"subject": "bertie"})
    assert _library_events(capsys) == []


def test_dry_run_put_does_not_touch_the_real_library(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=True, facets={"subject": None})
    asset = ctx.library.put(
        "ghost", _file(tmp_path, "g.png", b"GHOST"), facets={"subject": "ghost"}
    )
    # Visible within the run (overlay layered over real)...
    assert ctx.library.get("ghost").id == asset.id
    assert [a.id for a in ctx.library.find(facets={"subject": "ghost"})] == [asset.id]
    # ...but the real library is untouched — a fresh real store sees nothing.
    assert _real(tmp_path).get(asset.id) is None
    assert _real(tmp_path).find(facets={"subject": "ghost"}) == []


def test_dry_run_reads_layer_overlay_over_real(tmp_path: Path) -> None:
    # Seven found, one missing, generate that one, use all eight — the rehearsal (§7.9).
    real = _real(tmp_path, FacetSpec("subject"))
    seeded = real.put("found", _file(tmp_path, "f.png", b"FOUND"), facets={"subject": "cast"})
    ctx = _ctx(tmp_path, dry_run=True, facets={"subject": None})
    generated = ctx.library.put(
        "missing", _file(tmp_path, "m.png", b"MADE"), facets={"subject": "cast"}
    )
    ids = {a.id for a in ctx.library.find(facets={"subject": "cast"})}
    assert ids == {seeded.id, generated.id}  # both the real one and the overlay one
    assert _real(tmp_path).get(generated.id) is None  # overlay write did not reach real


def test_dry_run_annotate_does_not_mutate_the_real_library(tmp_path: Path) -> None:
    real = _real(tmp_path)
    asset = real.put("bertie", _file(tmp_path, "b.png", b"PIX"), kind="image")
    ctx = _ctx(tmp_path, dry_run=True)
    ctx.library.annotate(asset.id, caveats="rehearsed note")
    assert ctx.library.get(asset.id).caveats == "rehearsed note"  # visible in the run (overlay)
    assert _real(tmp_path).get(asset.id).caveats == ""  # real library untouched


def test_no_library_declared_is_none(tmp_path: Path) -> None:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    ctx = Context(
        ContextFile(
            settings={},
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
            ),
            workflow_version=_VERSION,
        )
    )
    assert ctx.library is None
