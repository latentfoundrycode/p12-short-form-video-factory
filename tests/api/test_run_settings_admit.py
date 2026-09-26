"""TASK-SSN-B1a contract (part A): admit_run forwards the new run settings to run_request.

The launch path carries three run-level settings chosen at launch time: `gates_auto` (approval
mode), `per_video_budget` (the owner's per-video cost cap, read by the B2 budget engine), and
`voice` (the narration voice, resolved by B4). `admit_run` must forward all three to
`run_request`, exactly as it already forwards `dry_run` (see test_admit_run_dry_run.py).

Pinned with a spy on run_request so it is deterministic and starts nothing. Supervisor-authored
frozen contract (RED-first); the builder implements app/api/runs.py + app/core/supervisor.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import app.api.runs as runs_mod


class _FakeRecord:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id


def _spy(captured: dict[str, Any]):
    def fake_run_request(
        workflow_dir: Path, *, on_started: Any = None, **kwargs: Any
    ) -> _FakeRecord:
        captured.clear()
        captured.update(kwargs)
        captured["workflow_dir"] = workflow_dir
        if on_started is not None:
            on_started("run-xyz")
        return _FakeRecord(run_id="run-xyz")

    return fake_run_request


def test_admit_run_forwards_run_settings(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(runs_mod, "run_request", _spy(captured))
    result = runs_mod.admit_run(
        tmp_path,
        params={"topic": "x"},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        gates_auto=True,
        per_video_budget=5.0,
        voice="narrator",
    )
    assert isinstance(result, runs_mod.AdmissionAccepted)
    assert captured["gates_auto"] is True
    assert captured["per_video_budget"] == 5.0
    assert captured["voice"] == "narrator"


def test_admit_run_defaults_run_settings(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(runs_mod, "run_request", _spy(captured))
    runs_mod.admit_run(
        tmp_path,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
    )
    # Unset settings default to autonomous-off, no per-video cap, and the default voice.
    assert captured["gates_auto"] is False
    assert captured["per_video_budget"] is None
    assert captured["voice"] == ""
