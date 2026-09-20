"""Frozen contract — Stage P, P-8d: admission refuses an unconfigured model param's provider.

A manifest param whose `options_from` is a models source (`sfvf.models`, `sfvf.models:image`,
`sfvf.models:video`, `<provider>.models`) carries a model id. When a run is launched, the admission
path resolves each such submitted model id and refuses (HTTP 422) if that model's provider is not
configured — a clean early refusal instead of a later `ctx.secret` failure mid-run. A model whose
provider IS configured proceeds; a param that is not a model source, and an unknown model id, do not
trip this check.

The refusal happens BEFORE `admit_run` spawns anything (the `run_request` spy is never called on a
refusal). The proceed cases monkeypatch `run_request` so nothing is actually launched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

import app.api.runs as runs_mod
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

_MODEL_PARAM = (
    '[[params]]\nkey = "model"\ntype = "select"\nlabel = "Model"\n'
    'options_from = "sfvf.models:video"'
)


class _FakeRecord:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


def _spy(calls: list[dict[str, Any]]):
    def fake_run_request(
        workflow_dir: Path, *, on_started: Any = None, **kwargs: Any
    ) -> _FakeRecord:
        calls.append({"workflow_dir": workflow_dir, **kwargs})
        if on_started is not None:
            on_started("run-xyz")
        return _FakeRecord(run_id="run-xyz")

    return fake_run_request


def _launch(client: TestClient, params: dict[str, Any]):
    return client.post(
        "/api/workflows/news-explainer/runs",
        json={"params": params, "video_count": 1, "concurrency": 1},
    )


def test_unconfigured_model_param_provider_is_refused_before_admission(
    tmp_path: Path, monkeypatch
) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml(extra=_MODEL_PARAM))
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    client = TestClient(create_app(tmp_path, secrets={}))  # byteplus not configured

    response = _launch(client, {"model": "byteplus/seedance-2.5"})
    assert response.status_code == 422
    assert "byteplus/seedance-2.5" in response.text
    assert calls == []  # refused before admit_run spawned anything


def test_configured_model_param_provider_proceeds(tmp_path: Path, monkeypatch) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml(extra=_MODEL_PARAM))
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    client = TestClient(create_app(tmp_path, secrets={"BYTEPLUS_ARK_API_KEY": "x"}))

    response = _launch(client, {"model": "byteplus/seedance-2.5"})
    assert response.status_code == 202
    assert calls  # admission proceeded


def test_unknown_model_id_is_not_refused_by_this_check(tmp_path: Path, monkeypatch) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml(extra=_MODEL_PARAM))
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    client = TestClient(create_app(tmp_path, secrets={}))

    response = _launch(client, {"model": "bogus/not-a-model"})
    assert response.status_code == 202  # unknown id is a different concern; not this refusal
    assert calls


def test_workflow_without_a_model_param_is_never_refused(tmp_path: Path, monkeypatch) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml())  # no model-source param
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    client = TestClient(create_app(tmp_path, secrets={}))

    response = _launch(client, {})
    assert response.status_code == 202
    assert calls
