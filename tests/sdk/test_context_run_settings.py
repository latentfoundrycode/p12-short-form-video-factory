"""TASK-SSN-B1a contract (part C): ctx exposes the new run settings for workflow/engine use.

per_video_budget (read by the B2 budget engine) and voice (resolved by B4) travel in context.json
as first-class ContextFile fields, mirrored onto the Context object like gates_auto / video_index.

Supervisor-authored frozen contract (RED-first); the builder implements sdk/sfvf/context.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sfvf.context import Context, ContextFile, ContextPaths


def _ctx(tmp_path: Path, **fields: Any) -> Context:
    video = tmp_path / "01"
    (video / "artifacts").mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp_path / "shared").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            workflow_id="wf",
            workflow_version="1.0.0",
            paths=ContextPaths(
                video=video,
                artifacts=video / "artifacts",
                steps=video / ".steps",
                shared=tmp_path / "shared",
            ),
            **fields,
        )
    )


def test_context_exposes_run_settings(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, per_video_budget=6.5, voice="narrator")
    assert ctx.per_video_budget == 6.5
    assert ctx.voice == "narrator"


def test_context_run_settings_defaults(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert ctx.per_video_budget is None
    assert ctx.voice == ""
