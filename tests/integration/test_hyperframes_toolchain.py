"""B-1a contract: the HyperFrames toolchain is installed and renders real video.

Stage B's local renderers are real (free, so they run in both dry and non-dry modes
per SDK §10). This proves the pinned `hyperframes` npm toolchain under `tools/hyperframes/`
actually renders an HTML composition to a valid house-format MP4 on this platform — the
load-bearing, least-CI-testable piece — before the `media.graphics` adapter wires onto it.

Skipped where the toolchain is not installed (`npm ci` under tools/hyperframes), so the
suite stays green on machines without it; CI installs it and runs this for real.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_HF_DIR = _REPO / "tools" / "hyperframes"
_HF_ENTRY = _HF_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
_PINNED_VERSION = "0.8.26"

_needs_toolchain = pytest.mark.skipif(
    not _HF_ENTRY.is_file() or shutil.which("node") is None,
    reason="hyperframes toolchain not installed (run `npm ci` in tools/hyperframes)",
)


def test_hyperframes_toolchain_is_pinned() -> None:
    # The toolchain config is committed and pins the exact hyperframes version, so every
    # environment (dev, Cursor, CI) installs the same renderer. node_modules is not
    # committed; the render test below exercises the installed toolchain.
    manifest = _HF_DIR / "package.json"
    assert manifest.is_file(), "tools/hyperframes/package.json must exist"
    assert (_HF_DIR / "package-lock.json").is_file(), "package-lock.json must exist"
    deps = json.loads(manifest.read_text(encoding="utf-8")).get("dependencies", {})
    assert deps.get("hyperframes") == _PINNED_VERSION


_HYPERFRAMES_JSON = json.dumps(
    {
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {
            "blocks": "compositions",
            "components": "compositions/components",
            "assets": "assets",
        },
    }
)

# A minimal composition that renders cleanly and fast: the GSAP timeline registered under
# window.__timelines[<composition-id>] is HyperFrames' timeline-readiness signal; without it
# the renderer waits ~45s for sub-timelines and warns. With it, a 1s clip renders in a few s.
_INDEX_HTML = """<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        width: 1080px; height: 1920px; overflow: hidden;
        background: #101418; font-family: sans-serif;
      }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main"
         data-start="0" data-duration="1" data-width="1080" data-height="1920">
      <div style="color:#fff;font-size:80px;padding:200px 60px">Toolchain smoke</div>
    </div>
    <script>
      window.__timelines = window.__timelines || {};
      window.__timelines["main"] = gsap.timeline({ paused: true });
    </script>
  </body>
</html>
"""


def _probe_dims(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(out.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


@_needs_toolchain
def test_hyperframes_renders_a_composition_to_mp4(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "hyperframes.json").write_text(_HYPERFRAMES_JSON, encoding="utf-8")
    (project / "index.html").write_text(_INDEX_HTML, encoding="utf-8")
    out = tmp_path / "out.mp4"

    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1"}
    subprocess.run(
        [
            "node",
            str(_HF_ENTRY),
            "render",
            str(project),
            "-o",
            str(out),
            "-f",
            "30",
            "--quiet",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )

    assert out.is_file()
    assert _probe_dims(out) == (1080, 1920)
