"""Contract for the `smoke_higgsfield` workflow — the minimal attended-first-run vehicle.

`smoke_higgsfield` is the smallest workflow that exercises the live Higgsfield path end to end (one
`media.video.generate` call on a Kling text-to-video model, one video) so the attended first
real run can validate the adapter + the budget breaker with a single generation. This test proves
the workflow is well-formed WITHOUT any spend or network:

- It declares `requires_keys = HIGGSFIELD_API_KEY`. This is the exact gap that broke the explainer's
  first real run (Speech-2b): without the declaration the §5.6 allowlist withholds the key and the
  real run dies with `KeyError` before doing anything useful. Assert it is present.
- Run in `dry_run` end to end: the SDK stubs the Higgsfield call (a local colour-bars clip, no key,
  no HTTP, no credits), so the run must reach `complete` and produce a video. This catches manifest,
  entrypoint, and Result-shape errors before we ever point it at the real API.

No live key, no network, no spend.
"""

from __future__ import annotations

import sys
from pathlib import Path

from app.core.env import EnvBlocked, EnvReady
from app.core.records import read_request, read_video
from app.core.supervisor import RunBusy, run_request
from app.registry.schema import parse_manifest_toml

_WORKFLOW = Path(__file__).resolve().parents[2] / "workflows" / "smoke_higgsfield"


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def test_smoke_higgsfield_declares_the_higgsfield_key() -> None:
    manifest = parse_manifest_toml((_WORKFLOW / "workflow.toml").read_text(encoding="utf-8"))
    names = {rk.name for rk in manifest.requires_keys}
    assert "HIGGSFIELD_API_KEY" in names, (
        "smoke_higgsfield must declare requires_keys HIGGSFIELD_API_KEY, or the allowlist "
        "withholds the key and the real run dies with KeyError (the Speech-2b lesson)."
    )


def test_smoke_higgsfield_dry_run_completes_and_produces_a_video(tmp_path: Path) -> None:
    result = run_request(
        _WORKFLOW,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        dry_run=True,
    )
    assert not isinstance(result, EnvBlocked | RunBusy)
    run_dir = next((tmp_path / "runs" / "smoke_higgsfield").iterdir())
    assert read_request(run_dir).status == "complete"
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.result is not None
    rel = video.result.get("video")
    assert isinstance(rel, str) and rel
    assert (run_dir / "01" / rel).is_file()
