"""E-2a contract: `media.graphics.check` — the composition-DOM self-review (§5.8 rows 6-8, §6.5).

`check()` loads the composition once in a headless browser and inspects the DOM for the four
failures that render perfectly yet make a video unusable, per SDK §6.5:

    | Element outside the viewport        | bounding box against the viewport            |
    | Element intersecting the safe zone  | bounding box against safe_zone_css() margins |
    | Truncated text                      | scrollWidth/scrollHeight exceeding client box|
    | Missing font                        | text nodes rendering at fallback metrics     |

It is deterministic, AI-free and free, so it runs in BOTH dry and non-dry mode (no paid spend) —
authors call it while iterating (§6.5). Each violation is a `{"kind", "detail"}` dict; a clean
composition returns `[]`. Fixtures are self-contained HTML (no external assets, no real spend).

Skipped where the pinned HyperFrames toolchain (tools/hyperframes, B-1a) is not installed, since
`check()` drives the same headless browser the renderer uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sfvf import media
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

# The house frame is 1080x1920 (portrait). The tiktok safe zone reserves the top 10% (192px),
# the right 15% (162px) and the bottom 15% (288px); the left is flush. So the safe area is
# x in [0, 918], y in [192, 1632]. Fixtures are placed relative to those bounds.

# A single heading well inside the safe area, in a system font, on one line — nothing wrong.
_CLEAN = (
    '<h1 style="position:absolute;left:120px;top:400px;width:600px;'
    'font-family:sans-serif;font-size:48px;color:#fff">Hello world</h1>'
)

# A content box pushed off the right edge of the frame — a chart drawn off-screen.
_OFFSCREEN = (
    '<div style="position:absolute;left:1300px;top:400px;width:200px;height:120px;'
    'background:#0af;color:#fff;font-family:sans-serif">chart</div>'
)

# A heading whose top sits at y=40, inside the reserved top margin (< 192px) — text that would
# render under the platform's own interface.
_IN_SAFE_ZONE = (
    '<h1 style="position:absolute;left:120px;top:40px;width:500px;'
    'font-family:sans-serif;font-size:40px;color:#fff">Title here</h1>'
)

# A long unbreakable word in a small box that clips its overflow — truncated mid-word.
_CLIPPED = (
    '<div style="position:absolute;left:120px;top:400px;width:140px;height:60px;'
    'overflow:hidden;white-space:nowrap;font-family:sans-serif;font-size:40px;color:#fff">'
    "Supercalifragilistic</div>"
)

# A heading whose declared face fails to load (bad url), so it renders at fallback metrics.
_MISSING_FONT = (
    '<style>@font-face{font-family:"GhostFace";src:url("does-not-exist-abc123.woff2")}</style>'
    '<h1 style="position:absolute;left:120px;top:400px;width:600px;'
    "font-family:'GhostFace',sans-serif;font-size:48px;color:#fff\">Ghosted heading</h1>"
)

# A full-frame background DIV behind a clean heading. The background legitimately fills the whole
# frame (including the reserved margins) and must NOT be flagged — it is not content.
_FULLFRAME_BG = (
    '<div style="position:absolute;inset:0;background:#123"></div>'
    '<h1 style="position:absolute;left:120px;top:400px;width:600px;'
    'font-family:sans-serif;font-size:48px;color:#fff">Body</h1>'
)

# A full-bleed background IMAGE (1x1 png stretched to the frame). A replaced element that fills the
# frame is an intentional background, not content escaping the frame or the safe zone.
_1PX_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
_FULLFRAME_IMG = (
    f'<img src="{_1PX_PNG}" '
    'style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover">'
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


def _check(video_dir: Path, html: str, *, safe_zone: bool = True, dry_run: bool = True) -> list:
    token = set_active(_ctx(video_dir, dry_run=dry_run))
    try:
        return media.graphics.check(html, safe_zone=safe_zone)
    finally:
        reset_active(token)


def _kinds(violations: list) -> set[str]:
    return {v["kind"] for v in violations}


def test_clean_composition_has_no_violations(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _check(video_dir, _CLEAN) == []


def test_violation_is_a_kind_detail_dict(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    violations = _check(video_dir, _OFFSCREEN)
    assert violations  # non-empty
    for v in violations:
        assert isinstance(v, dict)
        assert isinstance(v["kind"], str) and v["kind"]
        assert isinstance(v["detail"], str) and v["detail"]


def test_element_outside_viewport_is_flagged(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert "outside-viewport" in _kinds(_check(video_dir, _OFFSCREEN))


def test_element_in_safe_zone_is_flagged_when_enabled(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    kinds = _kinds(_check(video_dir, _IN_SAFE_ZONE, safe_zone=True))
    assert "safe-zone" in kinds
    assert "outside-viewport" not in kinds  # it is inside the frame, only in the margin


def test_safe_zone_not_checked_when_disabled(tmp_path: Path) -> None:
    # The only thing wrong with _IN_SAFE_ZONE is the safe-zone margin; with the check disabled
    # (safe_zone="none" workflows) it is clean. Locks that disabling checks nothing else.
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _check(video_dir, _IN_SAFE_ZONE, safe_zone=False) == []


def test_truncated_text_is_flagged(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert "text-clipped" in _kinds(_check(video_dir, _CLIPPED))


def test_missing_font_is_flagged(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert "missing-font" in _kinds(_check(video_dir, _MISSING_FONT))


def test_full_frame_background_div_is_not_flagged(tmp_path: Path) -> None:
    # A full-frame background element fills the frame and its reserved margins on purpose; flagging
    # it would false-fail legitimate paid renders. Only content is checked, not backgrounds.
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _check(video_dir, _FULLFRAME_BG) == []


def test_full_bleed_background_image_is_not_flagged(tmp_path: Path) -> None:
    # A replaced element (img) that fills the frame is an intentional full-bleed background, not
    # content escaping the viewport or sitting under the platform UI.
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _check(video_dir, _FULLFRAME_IMG) == []


def test_check_runs_in_non_dry_mode(tmp_path: Path) -> None:
    # check() is deterministic and free (no paid spend), so it runs for real in both modes — it
    # must not gate on dry_run the way the A-5 stub did.
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    assert _check(video_dir, _CLEAN, dry_run=False) == []


def test_check_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.graphics.check(_CLEAN)
