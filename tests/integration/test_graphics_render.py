"""B-1b contract: `media.graphics.render` renders real composed video via HyperFrames.

`render` is a local, free renderer, so per SDK §10 it runs REAL in BOTH dry and non-dry
modes (dry_run means "no paid spend", not "no rendering") — this is what produces real
composed video at zero cost with no live keys. It replaces the A-5 colour-bar stub: the
workflow's HTML is wrapped into a minimal HyperFrames project and rendered to a 1080x1920
MP4. Skipped where the pinned toolchain (tools/hyperframes, B-1a) is not installed.
"""

import subprocess
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_REPO = Path(__file__).resolve().parents[2]
_HF_ENTRY = (
    _REPO / "tools" / "hyperframes" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
)

pytestmark = pytest.mark.skipif(
    not _HF_ENTRY.is_file(),
    reason="hyperframes toolchain not installed (run `npm ci` in tools/hyperframes)",
)

# A composition that fills the frame with a distinctive solid red, so a sampled frame
# proves HyperFrames actually rendered THIS HTML (not a colour-bar stub or blank).
_RED_HTML = '<div style="position:absolute;inset:0;background:#ff0000"></div>'


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


def _render(video_dir: Path, html: str, duration_s: float, *, dry_run: bool = True) -> str:
    token = set_active(_ctx(video_dir, dry_run=dry_run))
    try:
        return media.graphics.render(html, duration_s=duration_s)
    finally:
        reset_active(token)


def _center_pixel(mp4: Path) -> tuple[int, int, int]:
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(mp4),
            "-vf",
            "crop=2:2:(iw-2)/2:(ih-2)/2,scale=1:1",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    px = out.stdout
    return px[0], px[1], px[2]


def test_render_produces_real_composed_video(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    out = _render(video_dir, _RED_HTML, 1.0)

    assert isinstance(out, str)
    assert not Path(out).is_absolute()
    clip = video_dir / out
    assert clip.is_file()
    probed = probe(clip)
    assert (probed.width, probed.height) == (1080, 1920)
    assert abs(probed.duration_s - 1.0) < 0.3

    # The rendered frame is the composition's red background — proof HyperFrames
    # rendered the supplied HTML, not a stub.
    r, g, b = _center_pixel(clip)
    assert r > 180
    assert g < 75
    assert b < 75


def test_render_resolves_video_relative_assets(tmp_path: Path) -> None:
    # A composition may reference video-relative assets the workflow wrote to
    # ctx.artifacts (e.g. the safe-zone CSS). The renderer must make them resolvable,
    # so the imported stylesheet actually applies to the rendered frame.
    video_dir = tmp_path / "01"
    artifacts = video_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "redbg.css").write_text(
        ".fill { position: absolute; inset: 0; background: #ff0000; }",
        encoding="utf-8",
    )
    html = '<style>@import url("artifacts/redbg.css");</style><div class="fill"></div>'
    out = _render(video_dir, html, 1.0)

    r, g, b = _center_pixel(video_dir / out)
    assert r > 180
    assert g < 75
    assert b < 75


def test_render_runs_in_non_dry_mode(tmp_path: Path) -> None:
    # A-5's stub raised NotImplementedError outside dry_run; the real renderer runs in
    # both modes (it is free/local, not a paid service).
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    out = _render(video_dir, _RED_HTML, 1.0, dry_run=False)
    clip = video_dir / out
    assert probe(clip).duration_s > 0


def test_render_is_deterministic_across_video_folders(tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    first = _render(a, "<h1>same</h1>", 1.0)
    second = _render(b, "<h1>same</h1>", 1.0)
    assert first == second
