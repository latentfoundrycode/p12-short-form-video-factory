"""E-2b contract: finalize() auto-runs the composition-DOM check (§5.8 rows 6-8, §6.5).

Per SDK §6.5: "finalize() runs [check()] automatically whenever a composition render is among its
inputs, and violations fail the video rather than warning." So `render()` must persist enough for
`finalize()` to recover the composition and re-check it, and `finalize()` fails the video when a
rendered composition has a violation. Unlike the E-1 content review (real-run only, since stub media
is static/silent), the composition HTML is real in a dry run too, so this check runs in BOTH modes —
it is exactly the cheap check §6.5 says to run "before spending anything on narration". A finalize
with no composition render among its inputs runs no composition check (non-composition workflows and
the A-6/E-1 finalize paths are unaffected).

Fixtures use a non-black full-frame background so the E-1 black-frame check passes and only the
composition check is exercised. Skipped where the pinned HyperFrames toolchain is not installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sfvf
from sfvf import media
from sfvf._ffmpeg import _binary, _run
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

# A non-black full-frame background so E-1's black-frame check passes; the composition check exempts
# it (full-frame, no text). Content sits on top.
_BG = '<div style="position:absolute;inset:0;background:#3a4a6a"></div>'
_CLEAN_COMP = (
    _BG + '<h1 style="position:absolute;left:120px;top:400px;width:600px;'
    'font-family:sans-serif;font-size:48px;color:#fff">Hello world</h1>'
)
# A chart pushed off the right edge of the frame — renders fine (clipped), but check() catches it.
_BAD_COMP = (
    _BG + '<div style="position:absolute;left:1300px;top:400px;width:200px;height:120px;'
    'background:#0af;color:#fff;font-family:sans-serif">chart</div>'
)


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


def _clip(path: Path, *, video: str, dur: float = 1.0) -> None:
    """A plain (non-composition) video via FFmpeg lavfi — no render(), so no composition sidecar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            video,
            "-t",
            str(dur),
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _render_then_finalize(video_dir: Path, composition_html: str, *, dry_run: bool) -> str:
    token = set_active(_ctx(video_dir, dry_run=dry_run))
    try:
        rendered = media.graphics.render(composition_html, duration_s=1.0)
        return sfvf.finalize(rendered)
    finally:
        reset_active(token)


def test_finalize_fails_when_rendered_composition_has_violations(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    with pytest.raises(RuntimeError, match="composition"):
        _render_then_finalize(video_dir, _BAD_COMP, dry_run=False)


def test_finalize_passes_when_rendered_composition_is_clean(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _render_then_finalize(video_dir, _CLEAN_COMP, dry_run=False) == "final.mp4"


def test_finalize_runs_composition_check_in_dry_run(tmp_path: Path) -> None:
    # The composition HTML is real even in a dry run, so the check runs in both modes (unlike the
    # E-1 content review, which a dry run skips).
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    with pytest.raises(RuntimeError, match="composition"):
        _render_then_finalize(video_dir, _BAD_COMP, dry_run=True)


def test_finalize_without_a_composition_render_runs_no_composition_check(tmp_path: Path) -> None:
    # No render() call → no composition among finalize's inputs → the composition check does not
    # run, so a plain moving video finalizes normally. Guards non-composition and A-6/E-1 paths.
    video_dir = tmp_path / "01"
    _clip(video_dir / "in.mp4", video="testsrc2=size=320x240:rate=30")
    token = set_active(_ctx(video_dir, dry_run=False))
    try:
        out = sfvf.finalize("in.mp4")
    finally:
        reset_active(token)
    assert out == "final.mp4"
