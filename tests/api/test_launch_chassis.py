"""Frozen contract - F3-6a: per-request chassis settings on launch (PRD §8.2).

R-028 Dry run is selectable per run: `dry_run` in the launch body reaches run_request.
R-027 Parallel steps per video is settable per request: `step_concurrency` reaches run_request;
      omitted -> the global default (Settings tab / env).
R-023 Number of videos is capped where the workflow declares `max_videos`: over the cap is a 422
      before anything spawns; the cap is exposed on the workflow list for the form.

Numeric/boolean fields are strict: a JSON bool is not an integer and an integer is not a bool.
No network, no spend (run_request is a spy; disk usage is stubbed).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.runs as runs_mod
import app.core.app_settings as app_settings_mod
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

_GB = 1024**3


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


@pytest.fixture
def calls(monkeypatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(recorded))
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _p: SimpleNamespace(total=500 * _GB, used=100 * _GB, free=400 * _GB),
    )
    return recorded


def _client(tmp_path: Path, extra: str = "") -> TestClient:
    write_plugin(tmp_path, "news-explainer", minimal_toml(extra=extra))
    return TestClient(create_app(tmp_path, secrets={}, runs_dir=tmp_path / "runs"))


def _launch(client: TestClient, **body: Any):
    payload: dict[str, Any] = {"params": {}, "video_count": 1, "concurrency": 1}
    payload.update(body)
    return client.post("/api/workflows/news-explainer/runs", json=payload)


# --------------------------------------------------------------------------- R-028 dry run


def test_dry_run_true_reaches_run_request(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path), dry_run=True)
    assert resp.status_code == 202
    assert calls and calls[0]["dry_run"] is True


def test_dry_run_defaults_to_false(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path))
    assert resp.status_code == 202
    assert calls and calls[0]["dry_run"] is False


@pytest.mark.parametrize("bad", [1, 0, "yes", "true", None])
def test_dry_run_must_be_a_real_bool(tmp_path: Path, calls, bad: Any) -> None:
    resp = _launch(_client(tmp_path), dry_run=bad)
    assert resp.status_code == 422
    assert calls == []


# --------------------------------------------------------------------------- R-027 parallel steps


def test_step_concurrency_reaches_run_request(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path), step_concurrency=3)
    assert resp.status_code == 202
    assert calls and calls[0]["step_concurrency"] == 3


def test_step_concurrency_omitted_uses_global_default(
    tmp_path: Path, calls, monkeypatch
) -> None:
    monkeypatch.setattr(app_settings_mod, "default_step_concurrency", lambda: 4)
    resp = _launch(_client(tmp_path))
    assert resp.status_code == 202
    assert calls and calls[0]["step_concurrency"] == 4


def test_step_concurrency_null_uses_global_default(tmp_path: Path, calls, monkeypatch) -> None:
    monkeypatch.setattr(app_settings_mod, "default_step_concurrency", lambda: 2)
    resp = _launch(_client(tmp_path), step_concurrency=None)
    assert resp.status_code == 202
    assert calls and calls[0]["step_concurrency"] == 2


@pytest.mark.parametrize("bad", [True, False, 0, -1, 1.5, "2"])
def test_step_concurrency_rejects_non_positive_int(tmp_path: Path, calls, bad: Any) -> None:
    resp = _launch(_client(tmp_path), step_concurrency=bad)
    assert resp.status_code == 422
    assert calls == []


# --------------------------------------------------------------------------- R-023 max videos


def test_video_count_over_max_videos_is_refused(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path, extra="max_videos = 3"), video_count=4)
    assert resp.status_code == 422
    assert calls == []  # refused before admit_run
    assert "3" in resp.text


def test_video_count_at_max_videos_proceeds(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path, extra="max_videos = 3"), video_count=3)
    assert resp.status_code == 202
    assert calls and calls[0]["video_count"] == 3


def test_no_max_videos_means_no_cap(tmp_path: Path, calls) -> None:
    resp = _launch(_client(tmp_path), video_count=50)
    assert resp.status_code == 202
    assert calls and calls[0]["video_count"] == 50


@pytest.mark.parametrize("bad", [True, False])
def test_video_count_rejects_bool(tmp_path: Path, calls, bad: Any) -> None:
    resp = _launch(_client(tmp_path), video_count=bad)
    assert resp.status_code == 422
    assert calls == []


def test_workflow_list_exposes_max_videos(tmp_path: Path) -> None:
    write_plugin(tmp_path, "capped", minimal_toml("capped", extra="max_videos = 3"))
    write_plugin(tmp_path, "uncapped", minimal_toml("uncapped"))
    client = TestClient(create_app(tmp_path, secrets={}, runs_dir=tmp_path / "runs"))
    resp = client.get("/api/workflows")
    assert resp.status_code == 200
    by_id = {w["id"]: w for w in resp.json()["workflows"]}
    assert by_id["capped"]["max_videos"] == 3
    assert by_id["uncapped"]["max_videos"] is None
