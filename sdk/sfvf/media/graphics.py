from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import TypedDict

from .._runtime import current_context
from ..context import Context
from .speech import WordTiming

_WIDTH = 1080
_HEIGHT = 1920
_FPS = 30
_DEFAULT_RENDER_TIMEOUT_S = 1800
_HEARTBEAT_PERIOD_S = 1.0

_SAFE_ZONE_CSS = """\
.safe-zone {
  padding-top: 10%;
  padding-right: 15%;
  padding-bottom: 15%;
  padding-left: 0;
}
"""


class Violation(TypedDict):
    kind: str
    detail: str


def render(composition_html: str, *, duration_s: float) -> str:
    ctx = current_context()
    sha = _sha8([composition_html, duration_s])
    dest, rel = _artifact(ctx, f"render-{sha}.mp4")
    _render_with_hyperframes(ctx, dest, composition_html, duration_s)
    return rel


def captions(audio: str, timings: list[WordTiming], style: str) -> str:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.graphics.captions: the HyperFrames adapter arrives in Stage B; "
            "run with dry_run=True"
        )
    sha = _sha8([audio, timings, style])
    dest, rel = _artifact(ctx, f"captions-{sha}.srt")
    dest.write_text(_srt_from_timings(timings), encoding="utf-8")
    return rel


def safe_zone_css() -> str:
    ctx = current_context()
    sha = _sha8(_SAFE_ZONE_CSS)
    dest, rel = _artifact(ctx, f"safe-zone-{sha}.css")
    dest.write_text(_SAFE_ZONE_CSS, encoding="utf-8")
    return rel


def check(composition_html: str, *, safe_zone: bool = True) -> list[Violation]:
    ctx = current_context()
    if not ctx.dry_run:
        raise NotImplementedError(
            "media.graphics.check: the HyperFrames adapter arrives in Stage B; "
            "run with dry_run=True"
        )
    _ = composition_html, safe_zone
    return []


def _render_with_hyperframes(
    ctx: Context, dest: Path, composition_html: str, duration_s: float
) -> None:
    entry = _hyperframes_entry()
    project = Path(tempfile.mkdtemp())
    try:
        (project / "hyperframes.json").write_text(
            json.dumps(
                {
                    "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
                    "paths": {
                        "blocks": "compositions",
                        "components": "compositions/components",
                        "assets": "assets",
                    },
                }
            ),
            encoding="utf-8",
        )
        (project / "index.html").write_text(
            _index_html(composition_html, duration_s),
            encoding="utf-8",
        )
        # HyperFrames serves the project over HTTP, so video-relative asset
        # references (e.g. @import url("artifacts/…")) only resolve if those
        # files live inside the project.
        shutil.copytree(ctx.paths.artifacts, project / "artifacts")
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("node is not on PATH")
        _run(
            [
                node,
                str(entry),
                "render",
                str(project),
                "-o",
                str(dest),
                "-f",
                str(_FPS),
                "--quiet",
            ]
        )
    finally:
        shutil.rmtree(project, ignore_errors=True)


def _hyperframes_entry() -> Path:
    override = os.environ.get("SFVF_HYPERFRAMES_ENTRY")
    entry = (
        Path(override)
        if override
        else (
            Path(__file__).resolve().parents[3]
            / "tools"
            / "hyperframes"
            / "node_modules"
            / "hyperframes"
            / "bin"
            / "hyperframes.mjs"
        )
    )
    if not entry.is_file():
        raise RuntimeError(
            f"HyperFrames toolchain not found at {entry}. "
            "Install it with `npm ci` in tools/hyperframes."
        )
    return entry


def _index_html(composition_html: str, duration_s: float) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en" data-resolution="portrait">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>\n'
        "    <style>\n"
        "      * { margin: 0; padding: 0; box-sizing: border-box; }\n"
        "      html, body {\n"
        f"        width: {_WIDTH}px; height: {_HEIGHT}px; overflow: hidden;\n"
        "        background: #101418; font-family: sans-serif;\n"
        "      }\n"
        "    </style>\n"
        "  </head>\n"
        "  <body>\n"
        '    <div id="root" data-composition-id="main"\n'
        f'         data-start="0" data-duration="{duration_s}"'
        f' data-width="{_WIDTH}" data-height="{_HEIGHT}">\n'
        f"      {composition_html}\n"
        "    </div>\n"
        "    <script>\n"
        "      window.__timelines = window.__timelines || {};\n"
        '      window.__timelines["main"] =\n'
        '        window.__timelines["main"] || gsap.timeline({ paused: true });\n'
        "    </script>\n"
        "  </body>\n"
        "</html>\n"
    )


def _run(command: list[str]) -> str:
    timeout_s = _hyperframes_timeout_s()
    try:
        proc = subprocess.Popen(  # noqa: S603
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"},
        )
    except OSError as exc:
        raise RuntimeError(f"command failed: {command}\n{exc}") from exc

    chunks: list[str] = []
    last_beat = 0.0
    ctx = current_context()

    def _beat() -> None:
        nonlocal last_beat
        now = time.monotonic()
        if now - last_beat < _HEARTBEAT_PERIOD_S:
            return
        last_beat = now
        ctx.heartbeat("render", waiting_on="hyperframes")

    def _read_stdout() -> None:
        stdout = proc.stdout
        if stdout is None:
            return
        try:
            for line in stdout:
                chunks.append(line)
                _beat()
        except (ValueError, OSError):
            return

    reader = threading.Thread(target=_read_stdout, daemon=True)
    reader.start()
    _beat()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill_process(proc)
                reader.join(timeout=5)
                raise RuntimeError(f"command failed: {command}\n{''.join(chunks)}")
            try:
                returncode = proc.wait(timeout=min(_HEARTBEAT_PERIOD_S, remaining))
                break
            except subprocess.TimeoutExpired:
                _beat()
        reader.join()
    finally:
        if proc.stdout is not None:
            proc.stdout.close()

    output = "".join(chunks)
    if returncode:
        raise RuntimeError(f"command failed: {command}\n{output}")
    return output


def _hyperframes_timeout_s() -> float:
    raw = os.environ.get("SFVF_HYPERFRAMES_TIMEOUT_S", str(_DEFAULT_RENDER_TIMEOUT_S))
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return float(_DEFAULT_RENDER_TIMEOUT_S)


def _kill_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)


def _sha8(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]


def _artifact(ctx: Context, filename: str) -> tuple[Path, str]:
    ctx.paths.artifacts.mkdir(parents=True, exist_ok=True)
    dest = ctx.paths.artifacts / filename
    return dest, dest.relative_to(ctx.paths.video).as_posix()


def _srt_from_timings(timings: list[WordTiming]) -> str:
    blocks: list[str] = []
    for index, cue in enumerate(timings, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(cue['start'])} --> {_srt_timestamp(cue['end'])}\n"
            f"{cue['word']}\n"
        )
    return "\n".join(blocks)


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(round(seconds * 1000), 0)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
