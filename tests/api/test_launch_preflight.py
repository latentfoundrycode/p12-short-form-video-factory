"""Frozen contract - F3-4/F3-5: Initiate is blocked with a specific message when disk is low
(R-036/R-072/R-158: refuse below 5 GB free) or a required key/program is missing (R-034), PRD §8.2.

The refusal is a 422 BEFORE admit_run spawns anything (the run_request spy is never called). A
configured key + present program + adequate disk proceed (202). No network, no spend.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

import app.api.runs as runs_mod
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


def _plenty_of_disk(monkeypatch) -> None:
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _p: SimpleNamespace(total=500 * _GB, used=100 * _GB, free=400 * _GB),
    )


def _launch(client: TestClient, workflow_id: str = "news-explainer"):
    return client.post(
        f"/api/workflows/{workflow_id}/runs",
        json={"params": {}, "video_count": 1, "concurrency": 1},
    )


# --------------------------------------------------------------------------- R-036 disk


def test_low_disk_refuses_launch(tmp_path: Path, monkeypatch) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml())
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _p: SimpleNamespace(total=500 * _GB, used=497 * _GB, free=3 * _GB),
    )
    client = TestClient(create_app(tmp_path, secrets={}))
    resp = _launch(client)
    assert resp.status_code == 422
    assert calls == []  # refused before admit_run
    assert "disk" in resp.text.lower() or "space" in resp.text.lower()


def test_low_disk_refuses_on_fresh_data_dir(tmp_path: Path, monkeypatch) -> None:
    """R-036: the runs directory does not exist until the first run is allocated. The disk
    check must fall back to an existing ancestor of that path (the volume the output lands
    on) and still refuse below 5 GB. A missing directory raises FileNotFoundError (a
    subclass of OSError); swallowing it as 'disk unreadable' lets a fresh install on a
    low-disk volume start, which is the exact case this preflight exists for.
    """
    write_plugin(tmp_path, "news-explainer", minimal_toml())
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))

    def fake_disk_usage(p: Any) -> SimpleNamespace:
        if not Path(p).exists():
            raise FileNotFoundError(p)
        return SimpleNamespace(total=500 * _GB, used=497 * _GB, free=3 * _GB)

    monkeypatch.setattr(shutil, "disk_usage", fake_disk_usage)
    runs_dir = tmp_path / "data" / "runs"  # nothing has created this yet
    assert not runs_dir.exists()
    client = TestClient(create_app(tmp_path, secrets={}, runs_dir=runs_dir))
    resp = _launch(client)
    assert resp.status_code == 422
    assert calls == []  # refused before admit_run, despite the missing runs dir
    assert "disk" in resp.text.lower() or "space" in resp.text.lower()


def test_adequate_disk_proceeds(tmp_path: Path, monkeypatch) -> None:
    write_plugin(tmp_path, "news-explainer", minimal_toml())
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    _plenty_of_disk(monkeypatch)
    client = TestClient(create_app(tmp_path, secrets={}))
    resp = _launch(client)
    assert resp.status_code == 202
    assert calls


# --------------------------------------------------------------------------- R-034 keys/programs


def test_missing_required_key_refuses_launch(tmp_path: Path, monkeypatch) -> None:
    toml = minimal_toml(extra='\n[[requires_keys]]\nname = "FOO_API_KEY"\nlabel = "Foo"')
    write_plugin(tmp_path, "news-explainer", toml)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    _plenty_of_disk(monkeypatch)
    client = TestClient(create_app(tmp_path, secrets={}))  # FOO_API_KEY not configured
    resp = _launch(client)
    assert resp.status_code == 422
    assert "FOO_API_KEY" in resp.text
    assert calls == []


def test_configured_required_key_proceeds(tmp_path: Path, monkeypatch) -> None:
    toml = minimal_toml(extra='\n[[requires_keys]]\nname = "FOO_API_KEY"\nlabel = "Foo"')
    write_plugin(tmp_path, "news-explainer", toml)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    _plenty_of_disk(monkeypatch)
    client = TestClient(create_app(tmp_path, secrets={"FOO_API_KEY": "x"}))
    resp = _launch(client)
    assert resp.status_code == 202
    assert calls


def test_missing_required_program_refuses_launch(tmp_path: Path, monkeypatch) -> None:
    toml = minimal_toml(extra='requires_binaries = ["definitely-not-a-real-binary-zzq"]')
    write_plugin(tmp_path, "news-explainer", toml)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(runs_mod, "run_request", _spy(calls))
    _plenty_of_disk(monkeypatch)
    client = TestClient(create_app(tmp_path, secrets={}))
    resp = _launch(client)
    assert resp.status_code == 422
    assert "definitely-not-a-real-binary-zzq" in resp.text
    assert calls == []
