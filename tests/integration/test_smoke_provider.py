"""Frozen contract — Stage P, P-11a: the generic `smoke_provider` attended-smoke workflow.

One workflow smokes any provider/model: a `kind` select (image|video) and a `model` select fed by
`options_from = "sfvf.models"`. It declares the live providers' API-key names so the §5.6 allowlist
grants them at smoke time (no admission check blocks on a missing key today — an unconfigured
provider fails at `ctx.secret`, before spend). It replaces the provider-specific `smoke_higgsfield`.

This pins: (1) the manifest declares every smokeable model's provider secret names; (2) a dry run
completes and produces a result file for BOTH an image model and a video model — no key, no network,
no spend (mirrors `test_smoke_higgsfield`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from sfvf.providers import list_models, resolve

from app.core.env import EnvBlocked, EnvReady, EnvResult
from app.core.records import read_request, read_video
from app.core.supervisor import RunBusy, run_request
from app.registry.schema import parse_manifest_toml

_WORKFLOW = Path(__file__).resolve().parents[2] / "workflows" / "smoke_provider"


def _ready(*_args: object, **_kwargs: object) -> EnvResult:
    return EnvReady(python=Path(sys.executable))


def test_smoke_provider_declares_every_smokeable_models_provider_keys() -> None:
    manifest = parse_manifest_toml((_WORKFLOW / "workflow.toml").read_text(encoding="utf-8"))
    declared = {rk.name for rk in manifest.requires_keys}
    for model in list_models():
        provider, _model = resolve(model.id)
        for name in provider.secret_names:
            assert name in declared, f"smoke_provider must declare {name!r} (for {model.id})"


def test_smoke_provider_has_a_kind_and_a_registry_backed_model_param() -> None:
    manifest = parse_manifest_toml((_WORKFLOW / "workflow.toml").read_text(encoding="utf-8"))
    params = {p.key: p for p in manifest.params}
    assert params["model"].options_from == "sfvf.models"
    assert set(params["kind"].options or []) == {"image", "video"}


def _run(tmp_path: Path, params: dict[str, object]):
    return run_request(
        _WORKFLOW,
        params=params,
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        ensure_env=_ready,
        dry_run=True,
    )


def _assert_completed(tmp_path: Path) -> None:
    run_dir = next((tmp_path / "runs" / "smoke_provider").iterdir())
    assert read_request(run_dir).status == "complete"
    video = read_video(run_dir / "01")
    assert video.status == "complete"
    assert video.result is not None
    rel = video.result.get("video")
    assert isinstance(rel, str) and rel
    assert (run_dir / "01" / rel).is_file()


def test_smoke_provider_dry_run_completes_for_a_video_model(tmp_path: Path) -> None:
    result = _run(tmp_path, {"kind": "video", "model": "byteplus/seedance-2.5"})
    assert not isinstance(result, EnvBlocked | RunBusy)
    _assert_completed(tmp_path)


def test_smoke_provider_dry_run_completes_for_an_image_model(tmp_path: Path) -> None:
    result = _run(tmp_path, {"kind": "image", "model": "openai/gpt-image-2"})
    assert not isinstance(result, EnvBlocked | RunBusy)
    _assert_completed(tmp_path)
