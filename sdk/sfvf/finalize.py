from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._ffmpeg import _binary, _run, probe
from ._review import content_review
from ._runtime import current_context

_HOUSE_WIDTH = 1080
_HOUSE_HEIGHT = 1920
_HOUSE_FPS = 30
_HOUSE_LUFS = -14
_FINAL_NAME = "final.mp4"
_VIDEO_FILTER = (
    f"scale={_HOUSE_WIDTH}:{_HOUSE_HEIGHT}:force_original_aspect_ratio=decrease,"
    f"pad={_HOUSE_WIDTH}:{_HOUSE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
    f"fps={_HOUSE_FPS},"
    "setsar=1"
)


def finalize(video: str, audio: str | None = None, captions: str | None = None) -> str:
    ctx = current_context()
    root = ctx.paths.video.resolve()
    video_path = _confine(root, video)
    audio_path = _confine(root, audio) if audio is not None else None
    captions_path = _confine(root, captions) if captions is not None else None

    dest = ctx.paths.video / _FINAL_NAME
    _apply_house_format(video_path, audio_path, captions_path, dest)
    _self_review(
        dest,
        expect_audio=audio is not None,
        expect_captions=captions is not None,
        dry_run=ctx.dry_run,
    )
    return _FINAL_NAME


def _confine(root: Path, rel: str) -> Path:
    resolved = (root / rel).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path escapes video folder: {rel}")
    if not resolved.is_file():
        raise FileNotFoundError(f"input does not exist: {rel}")
    return resolved


def _apply_house_format(
    video: Path,
    audio: Path | None,
    captions: Path | None,
    dest: Path,
) -> None:
    command = [_binary("ffmpeg"), "-y", "-fflags", "+bitexact", "-i", str(video)]
    next_index = 1
    audio_index: int | None = None
    captions_index: int | None = None
    if audio is not None:
        command.extend(["-i", str(audio)])
        audio_index = next_index
        next_index += 1
    if captions is not None:
        command.extend(["-i", str(captions)])
        captions_index = next_index

    command.extend(["-map", "0:v:0"])
    if audio_index is not None:
        command.extend(["-map", f"{audio_index}:a:0"])
    if captions_index is not None:
        command.extend(["-map", f"{captions_index}:s:0"])

    command.extend(["-vf", _VIDEO_FILTER, "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio_index is not None:
        # s16 after loudnorm: digital silence (dry-run stubs) makes loudnorm
        # emit NaN/Inf, which AAC then refuses to encode.
        command.extend(["-af", f"loudnorm=I={_HOUSE_LUFS},aformat=sample_fmts=s16", "-c:a", "aac"])
    else:
        command.append("-an")
    if captions_index is not None:
        command.extend(["-c:s", "mov_text"])
    command.extend(["-map_metadata", "-1", str(dest)])
    _run(command)


def _self_review(dest: Path, *, expect_audio: bool, expect_captions: bool, dry_run: bool) -> None:
    failures: list[str] = []
    structural: dict[str, Any] = {}
    content: dict[str, Any] | None = None
    probe_error: str | None = None
    structural_messages: list[str] = []
    content_messages: list[str] = []

    if not dest.is_file():
        detail = f"output missing: {dest}"
        failures.append(detail)
        probe_error = f"finalize self-review failed: {detail}"
    else:
        probed = probe(dest)
        has_captions = _has_subtitle(dest)
        if probed.width is None or probed.height is None:
            detail = "output has no video stream"
            failures.append(detail)
            probe_error = f"finalize self-review failed: {detail}"
            structural = {
                "duration_s": probed.duration_s,
                "has_audio": probed.has_audio,
                "has_captions": has_captions,
            }
        else:
            structural = {
                "duration_s": probed.duration_s,
                "width": probed.width,
                "height": probed.height,
                "has_audio": probed.has_audio,
                "has_captions": has_captions,
            }
            if (probed.width, probed.height) != (_HOUSE_WIDTH, _HOUSE_HEIGHT):
                detail = (
                    f"expected {_HOUSE_WIDTH}x{_HOUSE_HEIGHT}, got {probed.width}x{probed.height}"
                )
                failures.append(detail)
                structural_messages.append(detail)
            if probed.duration_s <= 0:
                detail = "duration is not > 0"
                failures.append(detail)
                structural_messages.append(detail)
            if probed.has_audio is not expect_audio:
                present = "present unexpectedly" if probed.has_audio else "missing"
                detail = f"audio stream {present}"
                failures.append(detail)
                structural_messages.append(detail)
            if has_captions is not expect_captions:
                present = "missing" if expect_captions else "present unexpectedly"
                detail = f"subtitle stream {present}"
                failures.append(detail)
                structural_messages.append(detail)
            if not dry_run:
                review = content_review(dest, expect_audio=expect_audio)
                content = {
                    "black": review.black,
                    "silent": review.silent,
                    "clipping": review.clipping,
                    "slideshow": review.slideshow,
                    "audio_mean_dbfs": review.audio_mean_dbfs,
                    "audio_peak_dbfs": review.audio_peak_dbfs,
                    "motion_score": review.motion_score,
                }
                content_messages.extend(review.failures)
                failures.extend(review.failures)

    checked, violations = _composition_review()
    composition_messages = [f"{item['kind']}: {item['detail']}" for item in violations]
    failures.extend(f"composition: {message}" for message in composition_messages)

    payload: dict[str, Any] = {
        "passed": not failures,
        "structural": structural,
        "content": content,
        "composition": {"checked": checked, "violations": violations},
        "failures": failures,
    }
    current_context().emit({"t": "self_review", **payload})

    if probe_error is not None:
        raise RuntimeError(probe_error)
    if structural_messages:
        raise RuntimeError("finalize self-review failed: " + "; ".join(structural_messages))
    if composition_messages:
        raise RuntimeError(
            "finalize composition self-review failed: " + "; ".join(composition_messages)
        )
    if content_messages:
        raise RuntimeError("finalize self-review failed: " + "; ".join(content_messages))


def _composition_review() -> tuple[int, list[dict[str, str]]]:
    # Runs whenever a composition render is among finalize's inputs (§6.5), in both dry and real
    # mode — the composition HTML is real even in a dry run. safe_zone follows the declared
    # `[output]` ("tiktok" | "none", §5.8/§6.5). `[output]` is not yet in the runtime Context, so
    # this uses the fixed house default (tiktok → safe_zone=True); when `[output]` is plumbed, pass
    # the workflow's declared safe_zone here instead of the hardcoded default.
    from .media.graphics import check

    artifacts = current_context().paths.artifacts
    if not artifacts.is_dir():
        return 0, []
    sidecars = sorted(artifacts.glob("render-*.html"))
    violations: list[dict[str, str]] = []
    for sidecar in sidecars:
        html = sidecar.read_text(encoding="utf-8")
        for violation in check(html, safe_zone=True):
            violations.append({"kind": violation["kind"], "detail": violation["detail"]})
    return len(sidecars), violations


def _has_subtitle(path: Path) -> bool:
    command = [
        _binary("ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "s",
        str(path),
    ]
    payload: object = json.loads(_run(command))
    if not isinstance(payload, dict):
        return False
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return False
    return any(_is_subtitle(item) for item in streams)


def _is_subtitle(item: object) -> bool:
    return isinstance(item, dict) and item.get("codec_type") == "subtitle"
