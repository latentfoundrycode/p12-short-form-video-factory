"""TASK-SSN-B1a contract (part B): the launch endpoint validates + persists the run settings.

`POST /api/workflows/{id}/runs` (LaunchBody) accepts three run-level settings and writes them into
every video's context.json:
  - `gates_auto: bool` (approval mode; default False)
  - `per_video_budget: float | None` (per-video cost cap; > 0 and within a sane max when set)
  - `voice: str` (narration voice id; default ""; when set it is a path-safe id, optionally with a
    single `preset:` prefix -- no path separators or traversal, delta S4/B4)
Bad settings are rejected with 422 before any run starts.

Supervisor-authored frozen contract (RED-first); the builder implements app/api/runs.py (LaunchBody
+ validation + threading), app/core/supervisor.py, sdk/sfvf/context.py.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.core.supervisor as supervisor_mod
from app.core.env import EnvReady
from app.main import create_app

STUBS = Path(__file__).resolve().parent.parent / "stubs"


@pytest.fixture(autouse=True)
def _clear_supervisor_state():
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()
    yield
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with supervisor_mod._lock:
            if not supervisor_mod._active and not supervisor_mod._runs:
                break
        time.sleep(0.05)
    with supervisor_mod._lock:
        supervisor_mod._active.clear()
        supervisor_mod._runs.clear()


def _ready(*_args: object, **_kwargs: object) -> EnvReady:
    return EnvReady(python=Path(sys.executable))


def _client(tmp_path: Path) -> TestClient:
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    dest = workflows_dir / "succeeds"
    shutil.copytree(STUBS / "succeeds", dest)
    (dest / "requirements.txt").write_text("", encoding="utf-8")
    return TestClient(
        create_app(
            workflows_dir=workflows_dir,
            runs_dir=tmp_path / "runs",
            ensure_env=_ready,  # type: ignore[arg-type]
        )
    )


def _read_video_context(runs_dir: Path, timeout: float = 15) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        succeeds = runs_dir / "succeeds"
        if succeeds.is_dir():
            for run_dir in succeeds.iterdir():
                ctx = run_dir / "01" / "context.json"
                if ctx.is_file():
                    return json.loads(ctx.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError("no video context.json was written")


def test_launch_persists_run_settings_into_context(tmp_path: Path) -> None:
    client = _client(tmp_path)
    launched = client.post(
        "/api/workflows/succeeds/runs",
        json={
            "params": {"topic": "test"},
            "video_count": 1,
            "concurrency": 1,
            "gates_auto": True,
            "per_video_budget": 5.0,
            "voice": "narrator",
        },
    )
    assert launched.status_code == 202
    context = _read_video_context(tmp_path / "runs")
    assert context["gates_auto"] is True
    assert context["per_video_budget"] == 5.0
    assert context["voice"] == "narrator"


def test_launch_defaults_run_settings(tmp_path: Path) -> None:
    client = _client(tmp_path)
    launched = client.post(
        "/api/workflows/succeeds/runs",
        json={"params": {"topic": "test"}, "video_count": 1, "concurrency": 1},
    )
    assert launched.status_code == 202
    context = _read_video_context(tmp_path / "runs")
    assert context["gates_auto"] is False
    assert context["per_video_budget"] is None
    assert context["voice"] == ""


@pytest.mark.parametrize("bad_budget", [0, -1, -0.5, 1_000_000_000.0])
def test_launch_rejects_bad_per_video_budget(tmp_path: Path, bad_budget: float) -> None:
    client = _client(tmp_path)
    resp = client.post(
        "/api/workflows/succeeds/runs",
        json={
            "params": {"topic": "test"},
            "video_count": 1,
            "concurrency": 1,
            "per_video_budget": bad_budget,
        },
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_launch_rejects_nonfinite_per_video_budget(tmp_path: Path, literal: str) -> None:
    # json.loads accepts the bare NaN/Infinity literals, so a raw body can smuggle a non-finite
    # per_video_budget past a naive `<= 0 or > MAX` bounds check (both comparisons are False for
    # NaN). A non-finite cap defeats every `spent > cap` test, so reject it at the boundary.
    client = _client(tmp_path)
    body = (
        '{"params": {"topic": "test"}, "video_count": 1, "concurrency": 1, '
        f'"per_video_budget": {literal}}}'
    )
    resp = client.post(
        "/api/workflows/succeeds/runs",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("bad_voice", ["../evil", "a/b", "..", ".", "voice id!", "a\\b"])
def test_launch_rejects_unsafe_voice(tmp_path: Path, bad_voice: str) -> None:
    client = _client(tmp_path)
    resp = client.post(
        "/api/workflows/succeeds/runs",
        json={
            "params": {"topic": "test"},
            "video_count": 1,
            "concurrency": 1,
            "voice": bad_voice,
        },
    )
    assert resp.status_code == 422


@pytest.mark.parametrize("good_voice", ["narrator", "preset:calm", "voice_2", "a.b-c"])
def test_launch_accepts_safe_voice(tmp_path: Path, good_voice: str) -> None:
    client = _client(tmp_path)
    resp = client.post(
        "/api/workflows/succeeds/runs",
        json={
            "params": {"topic": "test"},
            "video_count": 1,
            "concurrency": 1,
            "voice": good_voice,
        },
    )
    assert resp.status_code == 202
