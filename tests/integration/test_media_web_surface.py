"""Frozen contract — web-image-sourcing increment 1: the `sfvf.media.web` surface skeleton.

Per docs/DESIGN-web-image-sourcing.md §3. This increment establishes the SDK surface and its
dry-run behaviour ONLY — the real (non-dry-run) paths are not built yet and must raise
`NotImplementedError` (they are filled by later increments: commons search #2, fetch/safety #3,
check_relevance #4, source #5). No network is ever touched here.

Shapes (TypedDicts, read by subscript like `agents.Source`):
  * `ImageCandidate` — a search hit: source/url/thumbnail/licence/attribution/width/height/
    title/rank.
  * `Relevance` — a VLM verdict: relevant(bool)/score(float in [0,1])/reason(str).

Surface:
  * `search(query, *, sources=("commons",), limit=10, licence=None) -> list[ImageCandidate]`
  * `fetch(candidate) -> str`   (a workspace-relative path to the downloaded file)
  * `check_relevance(image, *, subject, model=...) -> Relevance`
  * `source(query, *, subject, sources=("commons",), want=1, consider=8, min_score=0.6,
            licence=None) -> list[SourcedImage]`   (path + candidate + relevance, design §3.2/§8)

Dry-run returns deterministic stubs with no network, mirroring `media.image.generate`'s stub
convention. Crucially `source()` in dry-run short-circuits to `want` `SourcedImage` results and
must NOT call the relevance gate (design §3.2); it honours `want` when `want <= consider`.
"""

import json
from pathlib import Path

import pytest
from sfvf import media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media import web as web_mod
from sfvf.media.web import ImageCandidate, Relevance, SourcedImage  # TypedDicts must exist


def _ctx(video_dir: Path, *, dry_run: bool) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _rel_file(video_dir: Path, rel: str) -> Path:
    assert isinstance(rel, str), "a produced path must be a string"
    assert not Path(rel).is_absolute(), "a produced path must be workspace-relative"
    target = video_dir / rel
    assert target.is_file(), f"expected a real stub file at {rel}"
    return target


_CANDIDATE_KEYS = {
    "source",
    "url",
    "thumbnail",
    "licence",
    "attribution",
    "width",
    "height",
    "title",
    "rank",
}


# --- active-context requirement -----------------------------------------------------------------


def test_web_surface_requires_an_active_context() -> None:
    # Every media.web entrypoint reads the active context and refuses without one.
    with pytest.raises(RuntimeError):
        media.web.search("red barn")
    with pytest.raises(RuntimeError):
        media.web.source("red barn", subject="a red barn")


# --- dry-run stubs (no network) -----------------------------------------------------------------


def test_search_dry_run_returns_candidate_stubs(tmp_path: Path) -> None:
    out = _run(_ctx(tmp_path, dry_run=True), lambda: media.web.search("red barn", limit=5))
    assert isinstance(out, list) and out, "search must return a non-empty list of candidates"
    assert len(out) <= 5, "search must honour limit"
    for cand in out:
        assert set(cand) >= _CANDIDATE_KEYS, "each candidate must carry the ImageCandidate keys"
        assert isinstance(cand["url"], str) and cand["url"]
        assert isinstance(cand["licence"], str)
    json.dumps(out)  # JSON-native
    # deterministic
    again = _run(_ctx(tmp_path, dry_run=True), lambda: media.web.search("red barn", limit=5))
    assert again == out


def test_fetch_dry_run_writes_a_workspace_relative_file(tmp_path: Path) -> None:
    def go():
        candidate = media.web.search("red barn", limit=1)[0]
        return media.web.fetch(candidate)

    rel = _run(_ctx(tmp_path, dry_run=True), go)
    _rel_file(tmp_path, rel)
    json.dumps(rel)


def test_fetch_dry_run_bytes_are_candidate_distinct(tmp_path: Path) -> None:
    # Distinct candidates must produce distinct stub BYTES, not identical content — else a dry-run
    # library intake (content-addressed) would collapse several sourced images into one asset and
    # lose distinct provenance. Content-distinctness must match filename-distinctness (both keyed on
    # the FULL per-url stem, not a truncated prefix). Regression for the r6 prefix collision: query
    # "collision-7091" ranks 1 & 9 had stems 1ffe0881 / 1ffe0824 sharing the 6-hex prefix 1ffe08.
    def go() -> list[str]:
        cands = media.web.search("collision-7091", limit=10)
        return [media.web.fetch(c) for c in cands]

    paths = _run(_ctx(tmp_path, dry_run=True), go)
    blobs = [_rel_file(tmp_path, p).read_bytes() for p in paths]
    assert len(blobs) == 10
    assert len(set(blobs)) == len(blobs), "each distinct candidate must produce distinct stub bytes"


def test_check_relevance_dry_run_returns_a_verdict(tmp_path: Path) -> None:
    def go():
        rel = media.web.fetch(media.web.search("red barn", limit=1)[0])
        return media.web.check_relevance(rel, subject="a red barn in a field")

    verdict = _run(_ctx(tmp_path, dry_run=True), go)
    assert set(verdict) >= {"relevant", "score", "reason"}
    assert isinstance(verdict["relevant"], bool)
    assert isinstance(verdict["score"], float) and 0.0 <= verdict["score"] <= 1.0
    assert isinstance(verdict["reason"], str)
    json.dumps(verdict)


def test_source_dry_run_returns_want_enriched_results(tmp_path: Path) -> None:
    # source() returns enriched SourcedImage results (path + candidate + relevance) so provenance is
    # preserved (design §3.2/§8). In dry-run it short-circuits to `want` real stub results WITHOUT
    # depending on the relevance gate, so a workflow dry-run sees real sourced results, not [].
    out = _run(
        _ctx(tmp_path, dry_run=True),
        lambda: media.web.source("red barn", subject="a red barn", want=2),
    )
    assert isinstance(out, list)
    assert len(out) == 2, "source must return `want` results in dry-run"
    for si in out:
        assert set(si) >= {"path", "candidate", "relevance"}, "SourcedImage shape"
        _rel_file(tmp_path, si["path"])
        assert set(si["candidate"]) >= _CANDIDATE_KEYS
        assert set(si["relevance"]) >= {"relevant", "score", "reason"}
    # results must not alias one shared mutable relevance dict (each is its own verdict)
    assert out[0]["relevance"] is not out[1]["relevance"], (
        "each result needs its own relevance dict"
    )
    json.dumps(out)


def test_source_dry_run_does_not_call_the_relevance_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The short-circuit is real: source() must NOT invoke check_relevance in dry-run. Monkeypatch it
    # to blow up and prove source() still returns `want` results without touching it.
    def _boom(*a: object, **k: object) -> Relevance:
        raise AssertionError("source() must not call check_relevance in dry-run")

    monkeypatch.setattr(web_mod, "check_relevance", _boom)
    out = _run(
        _ctx(tmp_path, dry_run=True),
        lambda: media.web.source("red barn", subject="a red barn", want=1),
    )
    assert len(out) == 1


def test_source_dry_run_honours_want_up_to_consider(tmp_path: Path) -> None:
    # In dry-run every stub "passes", so source() must return exactly `want` when `want <= consider`
    # — an artificial stub pool must not cap it below `want`. (Above `consider` it may return fewer,
    # per design §3.2.)
    for want in (1, 9, 12):
        out = _run(
            _ctx(tmp_path, dry_run=True),
            lambda w=want: media.web.source("red barn", subject="a red barn", want=w, consider=w),
        )
        assert len(out) == want, f"want={want} (== consider) must yield exactly {want} in dry-run"


def test_source_want_is_clamped_to_non_negative(tmp_path: Path) -> None:
    for want in (0, -1):
        out = _run(
            _ctx(tmp_path, dry_run=True),
            lambda w=want: media.web.source("red barn", subject="a red barn", want=w),
        )
        assert out == [], f"want={want} must yield no results, not negative-slice leakage"


def test_source_rejects_consider_above_the_fanout_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `consider` is the fan-out cost knob (each candidate = a fetch + a VLM check + a dry-run file).
    # It is bounded by _MAX_CONSIDER; exceeding it is an explicit ValueError, NOT a silent
    # truncation to a hidden pool size. Monkeypatched small to stay decoupled from the default.
    monkeypatch.setattr(web_mod, "_MAX_CONSIDER", 4, raising=True)
    ctx = _ctx(tmp_path, dry_run=True)
    with pytest.raises(ValueError):
        _run(ctx, lambda: media.web.source("red barn", subject="a red barn", want=5, consider=5))
    # At the ceiling it is honoured exactly.
    out = _run(ctx, lambda: media.web.source("red barn", subject="a red barn", want=4, consider=4))
    assert len(out) == 4


def test_search_validates_sources(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=True)
    with pytest.raises(ValueError):
        _run(ctx, lambda: media.web.search("red barn", sources=()))
    with pytest.raises(ValueError):
        _run(ctx, lambda: media.web.search("red barn", sources=("bogus",)))


def test_search_stub_reflects_the_requested_tier(tmp_path: Path) -> None:
    # A web-tier stub must present as the web tier with unknown licence (not commons/CC0), so a
    # workflow's dry-run sees tier-accurate provenance.
    out = _run(
        _ctx(tmp_path, dry_run=True),
        lambda: media.web.search("red barn", sources=("web",), limit=3),
    )
    assert out and all(c["source"] == "web" for c in out)
    assert all(c["licence"] == "unknown" for c in out)


# --- real path not built yet (skeleton) ---------------------------------------------------------


def test_real_paths_not_implemented_yet(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, dry_run=False)
    candidate = ImageCandidate(
        source="commons",
        url="https://example.invalid/x.jpg",
        thumbnail="https://example.invalid/x-t.jpg",
        licence="CC0-1.0",
        attribution="stub",
        width=800,
        height=600,
        title="x",
        rank=0,
    )
    with pytest.raises(NotImplementedError):
        _run(ctx, lambda: media.web.search("red barn"))
    with pytest.raises(NotImplementedError):
        _run(ctx, lambda: media.web.fetch(candidate))
    with pytest.raises(NotImplementedError):
        _run(ctx, lambda: media.web.check_relevance("shot.png", subject="a red barn"))
    with pytest.raises(NotImplementedError):
        _run(ctx, lambda: media.web.source("red barn", subject="a red barn"))
    # keep the Relevance/SourcedImage TypedDicts referenced so the imports are load-bearing
    _ = Relevance(relevant=True, score=1.0, reason="ok")
    _ = SourcedImage(
        path="web-x.png",
        candidate=candidate,
        relevance=Relevance(relevant=True, score=1.0, reason="ok"),
    )
