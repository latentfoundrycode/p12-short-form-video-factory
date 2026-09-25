from __future__ import annotations

from typing import Any

from .._ffmpeg import _binary, _run
from .._runtime import current_context
from ..emit import heartbeat_during
from .graphics import _artifact, _sha8

_NORM = "aresample=44100,aformat=channel_layouts=stereo"


def trim(video: str, start: float, end: float) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-trim-{_sha8([video, start, end])}.mp4")
    abs_in = str((ctx.paths.video / video).resolve())
    with heartbeat_during("edit", waiting_on="ffmpeg"):
        _client().trim(abs_in, start=start, end=end, output=str(dest))
    return rel


def mix(
    narration: str,
    *,
    music: str | None = None,
    sfx: list[tuple[str, float]] | None = None,
    duck: bool = True,
) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-mix-{_sha8([narration, music, sfx, duck])}.m4a")
    inputs: list[str] = [str((ctx.paths.video / narration).resolve())]
    if music is not None:
        inputs.append(str((ctx.paths.video / music).resolve()))
    sfx_list = sfx or []
    for path, _ in sfx_list:
        inputs.append(str((ctx.paths.video / path).resolve()))

    filter_complex = _mix_filter(music is not None, sfx_list, duck)
    args = [_binary("ffmpeg"), "-y", "-loglevel", "error"]
    for inp in inputs:
        args.extend(["-i", inp])
    args.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(dest),
        ]
    )
    with heartbeat_during("edit", waiting_on="ffmpeg"):
        _run(args)
    return rel


def _mix_filter(has_music: bool, sfx: list[tuple[str, float]], duck: bool) -> str:
    if not has_music and not sfx:
        return f"[0:a]{_NORM}[out]"

    parts: list[str] = []
    mix_labels: list[str] = []
    next_input = 1

    if has_music:
        music_idx = next_input
        next_input += 1
        if duck:
            parts.append(f"[0:a]{_NORM},asplit=2[nsc][nmix]")
            parts.append(
                f"[{music_idx}:a]{_NORM}[nmusic_in];"
                f"[nmusic_in][nsc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=250[duckm]"
            )
            mix_labels.append("[nmix]")
            mix_labels.append("[duckm]")
        else:
            parts.append(f"[0:a]{_NORM}[narr]")
            parts.append(f"[{music_idx}:a]{_NORM}[mus]")
            mix_labels.extend(["[narr]", "[mus]"])
    else:
        parts.append(f"[0:a]{_NORM}[narr]")
        mix_labels.append("[narr]")

    for i, (_, at) in enumerate(sfx):
        sfx_idx = next_input + i
        label = f"sfx{i}"
        delay_ms = round(at * 1000)
        parts.append(f"[{sfx_idx}:a]{_NORM},adelay={delay_ms}:all=1[{label}]")
        mix_labels.append(f"[{label}]")

    k = len(mix_labels)
    parts.append(f"{''.join(mix_labels)}amix=inputs={k}:duration=longest:normalize=0[out]")
    return ";".join(parts)


def cut(clips: list[str], *, transitions: list[str] | None = None) -> str:
    ctx = current_context()
    dest, rel = _artifact(ctx, f"edit-cut-{_sha8([clips, transitions])}.mp4")
    abs_clips = [str((ctx.paths.video / clip).resolve()) for clip in clips]
    with heartbeat_during("edit", waiting_on="ffmpeg"):
        _client().merge(abs_clips, transitions=transitions, output=str(dest))
    return rel


def _client() -> Any:
    try:
        from kinocut import Client
    except ImportError as exc:  # optional `sfvf[edit]` extra
        raise RuntimeError(
            "media.edit requires the 'kinocut' package. Install the SDK 'edit' extra: "
            "pip install 'sfvf[edit]' (or pip install kinocut==1.15.1)."
        ) from exc
    return Client()
