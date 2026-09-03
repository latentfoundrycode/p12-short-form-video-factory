"""B-2 contract: ``media.edit.trim`` + ``media.edit.cut`` on real Kinocut.

``edit`` wraps Kinocut's deterministic, local/free, FFmpeg-backed programmatic ``Client``,
so per SDK §10 it runs REAL in BOTH dry and non-dry modes (``dry_run`` means "no paid
spend", not "no editing"). Inputs are video-relative path strings (resolved against
``ctx.paths.video``); outputs are video-relative path strings the step cache
content-addresses. ``mix``/duck is intentionally out of scope for B-2 (deferred until a
workflow needs audio mixing). Skipped where the ``kinocut`` package or ``ffmpeg`` is not
installed (CI installs both, so these RUN there).
"""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
from sfvf import media
from sfvf._ffmpeg import probe
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_HAS_KINOCUT = importlib.util.find_spec("kinocut") is not None
_HAS_FFMPEG = shutil.which("ffmpeg") is not None

pytestmark = pytest.mark.skipif(
    not (_HAS_KINOCUT and _HAS_FFMPEG),
    reason="kinocut/ffmpeg not installed (install the `sfvf[edit]` extra + ffmpeg)",
)


def _ctx(video_dir: Path, *, dry_run: bool = True) -> Context:
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


def _solid_clip(dest: Path, color: str, seconds: float) -> None:
    """Write a real solid-colour MP4 so a sampled frame proves the edit's content."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=256x256:r=30:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )


def _pixel_at(mp4: Path, at_s: float) -> tuple[int, int, int]:
    out = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            str(at_s),
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


def _trim(video_dir: Path, clip: str, start: float, end: float, *, dry_run: bool = True) -> str:
    token = set_active(_ctx(video_dir, dry_run=dry_run))
    try:
        return media.edit.trim(clip, start, end)
    finally:
        reset_active(token)


def _cut(
    video_dir: Path,
    clips: list[str],
    *,
    transitions: list[str] | None = None,
    dry_run: bool = True,
) -> str:
    token = set_active(_ctx(video_dir, dry_run=dry_run))
    try:
        return media.edit.cut(clips, transitions=transitions)
    finally:
        reset_active(token)


def test_trim_produces_shorter_clip(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    _solid_clip(video_dir / "artifacts" / "red.mp4", "red", 3.0)

    out = _trim(video_dir, "artifacts/red.mp4", 0.0, 1.0)

    assert isinstance(out, str)
    assert not Path(out).is_absolute()
    clip = video_dir / out
    assert clip.is_file()
    assert abs(probe(clip).duration_s - 1.0) < 0.3


def test_cut_concatenates_clips_in_order(tmp_path: Path) -> None:
    # Two 1s solid clips concatenated → one ~2s clip whose first second is the first
    # clip's colour and second second is the second clip's colour. Proves cut really
    # joined the supplied clips, in order — not a stub or a single passthrough.
    video_dir = tmp_path / "01"
    _solid_clip(video_dir / "artifacts" / "red.mp4", "red", 1.0)
    _solid_clip(video_dir / "artifacts" / "blue.mp4", "blue", 1.0)

    out = _cut(video_dir, ["artifacts/red.mp4", "artifacts/blue.mp4"])

    assert isinstance(out, str)
    assert not Path(out).is_absolute()
    clip = video_dir / out
    assert clip.is_file()
    assert abs(probe(clip).duration_s - 2.0) < 0.4

    r0, g0, b0 = _pixel_at(clip, 0.3)
    assert r0 > 180 and g0 < 75 and b0 < 75  # first clip: red
    r1, g1, b1 = _pixel_at(clip, 1.7)
    assert b1 > 180 and r1 < 75 and g1 < 75  # second clip: blue


def test_edit_runs_in_non_dry_mode(tmp_path: Path) -> None:
    # edit is free/local, so unlike the paid stubs it runs REAL in both modes.
    video_dir = tmp_path / "01"
    _solid_clip(video_dir / "artifacts" / "red.mp4", "red", 2.0)

    out = _trim(video_dir, "artifacts/red.mp4", 0.0, 1.0, dry_run=False)
    assert probe(video_dir / out).duration_s > 0


def test_edit_output_is_video_relative(tmp_path: Path) -> None:
    # The returned path must be relative to ctx.paths.video (POSIX) and land under it,
    # so it survives the JSON step cache and resolves in later steps.
    video_dir = tmp_path / "01"
    _solid_clip(video_dir / "artifacts" / "red.mp4", "red", 2.0)

    out = _trim(video_dir, "artifacts/red.mp4", 0.0, 1.0)
    assert "\\" not in out
    resolved = (video_dir / out).resolve()
    assert resolved.is_relative_to(video_dir.resolve())


def test_trim_is_deterministic_across_video_folders(tmp_path: Path) -> None:
    # Same (clip path, start, end) → same relative output path regardless of video
    # folder, so the step cache is stable across runs (mirrors graphics.render).
    a = tmp_path / "a"
    b = tmp_path / "b"
    _solid_clip(a / "artifacts" / "red.mp4", "red", 2.0)
    _solid_clip(b / "artifacts" / "red.mp4", "red", 2.0)

    first = _trim(a, "artifacts/red.mp4", 0.0, 1.0)
    second = _trim(b, "artifacts/red.mp4", 0.0, 1.0)
    assert first == second


def test_edit_requires_active_context() -> None:
    # Like the rest of the SDK surface (graphics/agents/finalize), edit reads the ambient
    # context, so calling it with no active context raises RuntimeError rather than
    # silently doing nothing.
    with pytest.raises(RuntimeError):
        media.edit.trim("artifacts/red.mp4", 0.0, 1.0)
