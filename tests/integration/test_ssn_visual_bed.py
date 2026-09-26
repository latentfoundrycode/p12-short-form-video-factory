"""TASK-SSN-D2 contract: source a per-beat visual bed (mostly Ken-Burns stills + 1-2 clips).

The narration is segmented into time BEATS; each beat gets a visual: a static image (a free-commons
web image via `media.web.source`, relevance-checked, or an AI still via `media.image.generate`) or
a short AI clip (`media.video.generate`, ~4-5 s) for the hook + at most one hypothetical. The
balanced default is MOSTLY STILLS + AT MOST 2 CLIPS (design 3.5, under-$8 budget). Static images are
flagged for KEN-BURNS pan/zoom so the video is not a static slideshow (D3 renders the motion and the
non-dry `finalize.content_review` checks it). Web-image source URLs are collected for the desc.

D2 SOURCES the bed; D3 composites it. This pins the sourcing in dry-run (media providers stub).
Supervisor-authored (RED-first); the builder adds `_beats` + `_source_visual_bed` to main.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_bed_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ctx(tmp: Path) -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=True,
            workflow_id="sensational-science-news",
            video_index=1,
            video_count=1,
            paths=ContextPaths(
                video=tmp / "01",
                artifacts=tmp / "01" / "artifacts",
                steps=tmp / "01" / ".steps",
                shared=tmp / "01",
                cache=tmp / "cache",
                library=tmp / "lib",
            ),
        )
    )


def test_beats_segment_the_duration_contiguously() -> None:
    main = _load_main()
    beats = main._beats(75.0)
    assert len(beats) >= 4, "a 75s video needs several beats, not one static image"
    assert beats[0]["start"] == 0.0
    assert abs(beats[-1]["end"] - 75.0) < 0.01
    # contiguous, non-overlapping, increasing
    from itertools import pairwise

    for a, b in pairwise(beats):
        assert a["end"] <= b["start"] + 0.01
        assert a["end"] > a["start"]


def test_source_visual_bed_mostly_stills_at_most_two_clips(tmp_path: Path) -> None:
    main = _load_main()
    ctx = _ctx(tmp_path)
    beats = main._beats(75.0)
    token = set_active(ctx)
    try:
        bed = main._source_visual_bed(ctx, subject="Gut bacteria and memory", beats=beats)
    finally:
        reset_active(token)
    assets = bed["assets"]
    assert len(assets) == len(beats), "one visual per beat"
    kinds = [a["kind"] for a in assets]
    clips = [k for k in kinds if k == "clip"]
    statics = [k for k in kinds if k in ("still", "web")]
    assert len(clips) <= 2, f"balanced default is at most 2 clips, got {len(clips)}"
    assert len(statics) > len(clips), "mostly stills"
    # every asset resolves to a produced artifact path (dry-run stub files exist)
    for a in assets:
        p = ctx.paths.video / a["path"]
        assert p.is_file(), f"missing bed artifact: {a['path']}"


def test_source_visual_bed_stills_get_ken_burns_clips_do_not(tmp_path: Path) -> None:
    main = _load_main()
    ctx = _ctx(tmp_path)
    beats = main._beats(75.0)
    token = set_active(ctx)
    try:
        bed = main._source_visual_bed(ctx, subject="A finding", beats=beats)
    finally:
        reset_active(token)
    for a in bed["assets"]:
        if a["kind"] in ("still", "web"):
            assert a.get("ken_burns") is True, "static images must pan/zoom (not a slideshow)"
        else:  # clip already moves
            assert a.get("ken_burns") is not True


def test_source_visual_bed_collects_web_source_urls(tmp_path: Path) -> None:
    main = _load_main()
    ctx = _ctx(tmp_path)
    beats = main._beats(75.0)
    token = set_active(ctx)
    try:
        bed = main._source_visual_bed(ctx, subject="A finding", beats=beats)
    finally:
        reset_active(token)
    urls = bed["source_urls"]
    assert isinstance(urls, list)
    web_assets = [a for a in bed["assets"] if a["kind"] == "web"]
    # in dry-run commons search returns stub candidates, so web images are used and their URLs kept
    if web_assets:
        assert urls, "web-sourced images must contribute their source URLs for the description"
        for a in web_assets:
            assert a.get("url"), "a web asset carries its source URL"
