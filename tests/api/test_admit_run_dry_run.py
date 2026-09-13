"""F-5 contract (part A): `admit_run` threads `dry_run` through to `run_request`.

Architecture §5.7 / the scheduler owner decision (2026-09-12): a scheduled run defaults to a free
**dry run** unless the entry opts into real spend; the engine computes
`dry_run = not allow_real_spend` and hands it to its `start` callable. For a scheduled run to
launch dry, the admission path (`app.api.runs.admit_run`) must forward `dry_run` to
`app.core.supervisor.run_request` (which already honours it, running under the `dry` cache mode and
skipping the real library + budget preflight). Before F-5, `admit_run` took no `dry_run` and always
launched a real run.

This pins the threading with a spy on `run_request`, so it is deterministic and starts nothing.
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


def test_admit_run_forwards_dry_run_true(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(runs_mod, "run_request", _spy(captured))
    result = runs_mod.admit_run(
        tmp_path,
        params={"topic": "x"},
        video_count=2,
        concurrency=1,
        runs_dir=tmp_path / "runs",
        dry_run=True,
    )
    assert isinstance(result, runs_mod.AdmissionAccepted)
    assert result.run_id == "run-xyz"
    assert captured["dry_run"] is True
    # The other run settings are still forwarded unchanged.
    assert captured["params"] == {"topic": "x"}
    assert captured["video_count"] == 2


def test_admit_run_defaults_dry_run_false(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(runs_mod, "run_request", _spy(captured))
    result = runs_mod.admit_run(
        tmp_path,
        params={},
        video_count=1,
        concurrency=1,
        runs_dir=tmp_path / "runs",
    )
    assert isinstance(result, runs_mod.AdmissionAccepted)
    # A run with no explicit dry_run stays a real run — the HTTP launch path is unchanged.
    assert captured["dry_run"] is False
