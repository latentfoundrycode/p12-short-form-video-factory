from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MediaProbe:
    duration_s: float
    width: int | None
    height: int | None
    has_audio: bool


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def silent_audio(dest: Path, *, duration_s: float) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t",
            str(duration_s),
            "-c:a",
            "aac",
            "-map_metadata",
            "-1",
            str(dest),
        ]
    )
    return dest


def color_bars(dest: Path, *, duration_s: float, width: int, height: int, fps: int) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            f"smptebars=size={width}x{height}:rate={fps}",
            "-t",
            str(duration_s),
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-an",
            "-map_metadata",
            "-1",
            str(dest),
        ]
    )
    return dest


def solid_image(dest: Path, *, width: int, height: int, color: str = "gray") -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            _binary("ffmpeg"),
            "-y",
            "-fflags",
            "+bitexact",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={width}x{height}",
            "-frames:v",
            "1",
            "-map_metadata",
            "-1",
            str(dest),
        ]
    )
    return dest


def probe(path: Path) -> MediaProbe:
    command = [
        _binary("ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    payload: object = json.loads(_run(command))
    if not isinstance(payload, dict):
        raise RuntimeError(f"command failed: {command}\nffprobe did not return a JSON object")
    width, height = _first_video_size(payload)
    return MediaProbe(
        duration_s=_duration_s(payload),
        width=width,
        height=height,
        has_audio=_has_audio(payload),
    )


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(f"{name} is not on PATH")
    return found


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        raise RuntimeError(f"command failed: {command}\n{stderr}") from exc
    except OSError as exc:
        raise RuntimeError(f"command failed: {command}\n{exc}") from exc
    return completed.stdout


def _duration_s(payload: dict[str, Any]) -> float:
    format_info = payload.get("format")
    if not isinstance(format_info, dict):
        return 0.0
    raw = format_info.get("duration")
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _first_video_size(payload: dict[str, Any]) -> tuple[int | None, int | None]:
    for stream in _streams(payload):
        if stream.get("codec_type") != "video":
            continue
        return _as_int(stream.get("width")), _as_int(stream.get("height"))
    return None, None


def _has_audio(payload: dict[str, Any]) -> bool:
    return any(stream.get("codec_type") == "audio" for stream in _streams(payload))


def _streams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("streams")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
