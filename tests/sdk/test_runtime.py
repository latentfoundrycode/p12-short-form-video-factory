"""A-1 contract: the ambient-context bridge and ctx.params.

Provided functions (sfvf.agents / sfvf.media.*) are called as `agents.llm(...)`
without being handed `ctx`, so they need ambient access to the active Context
(for `dry_run`, `paths`, etc.). The runner must publish the Context for exactly
the duration of the entrypoint, and clear it afterwards.
"""

import json
from pathlib import Path

import pytest
from sfvf._runtime import current_context, reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.runner import _run

STUBS = Path(__file__).resolve().parent.parent / "stubs"


def _context_file(video_dir: Path, settings: dict[str, object]) -> ContextFile:
    return ContextFile(
        settings=settings,
        paths=ContextPaths(
            video=video_dir,
            artifacts=video_dir / "artifacts",
            steps=video_dir / ".steps",
            shared=video_dir,
        ),
    )


def test_current_context_raises_when_none() -> None:
    with pytest.raises(RuntimeError):
        current_context()


def test_set_active_publishes_and_reset_restores(tmp_path: Path) -> None:
    ctx = Context(_context_file(tmp_path, {"topic": "x"}))
    token = set_active(ctx)
    try:
        assert current_context() is ctx
    finally:
        reset_active(token)
    with pytest.raises(RuntimeError):
        current_context()


def test_set_active_nests(tmp_path: Path) -> None:
    outer = Context(_context_file(tmp_path / "a", {"n": 1}))
    inner = Context(_context_file(tmp_path / "b", {"n": 2}))
    t_outer = set_active(outer)
    t_inner = set_active(inner)
    assert current_context() is inner
    reset_active(t_inner)
    assert current_context() is outer
    reset_active(t_outer)


def test_ctx_params_is_settings(tmp_path: Path) -> None:
    ctx = Context(_context_file(tmp_path, {"topic": "hello", "n": 3}))
    assert ctx.params == {"topic": "hello", "n": 3}


def test_runner_publishes_active_context_during_entrypoint(tmp_path: Path) -> None:
    video_dir = tmp_path / "01"
    video_dir.mkdir()
    context_path = video_dir / "context.json"
    context_path.write_text(
        json.dumps(_context_file(video_dir, {"topic": "hi"}).model_dump(mode="json")),
        encoding="utf-8",
    )
    result_path = video_dir / "result.json"

    _run(
        STUBS / "uses_runtime",
        context_path,
        entry="entrypoint",
        result_path=result_path,
    )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["ambient_is_ctx"] is True
    assert result["params_topic"] == "hi"
    # The bridge must be cleared once the entrypoint returns.
    with pytest.raises(RuntimeError):
        current_context()
