"""Reviewer-authored contract for `ctx.step` (SDK-2), the cached step boundary.

Workflow SDK §4.5, §5.1-§5.5: a step consults the cache (hit returns instantly, body not
run), records via a `step` event (family name, short key, label, status), the `label` is
display-only (never affects the key), files returned are stored/restored by content, and a
body that raises is not cached.
"""

import json
from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths


def _make_ctx(tmp_path: Path, *, version: str = "1.0.0") -> Context:
    video = tmp_path / "01"
    artifacts = video / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    steps = video / ".steps"
    steps.mkdir(parents=True, exist_ok=True)
    shared = tmp_path / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            paths=ContextPaths(
                video=video,
                artifacts=artifacts,
                steps=steps,
                shared=shared,
                cache=tmp_path / "cache",
            ),
            workflow_version=version,
        )
    )


def _emitted_events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_step_misses_then_body_runs_and_result_is_returned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _make_ctx(tmp_path)
    ran = []
    with ctx.step("write-script", inputs={"topic": "x"}, label="Script") as step:
        assert step.cached is False
        ran.append(1)
        step.set({"script": "hi", "words": 2})
        result = step.value
    assert result == {"script": "hi", "words": 2}
    assert ran == [1]
    events = [e for e in _emitted_events(capsys) if e.get("t") == "step"]
    assert len(events) == 1
    assert events[0]["name"] == "write-script"
    assert events[0]["label"] == "Script"
    assert events[0]["status"] == "ok"
    assert isinstance(events[0]["key"], str) and events[0]["key"]


def test_step_hit_returns_cached_without_running_body_and_ignores_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _make_ctx(tmp_path)
    with first.step("write-script", inputs={"topic": "x"}, label="Script") as step:
        step.set({"script": "hi"})
    capsys.readouterr()  # drop the miss's output

    # A fresh Context on the same cache; a DIFFERENT label must still hit (label not in key).
    second = _make_ctx(tmp_path)
    ran = []
    with second.step("write-script", inputs={"topic": "x"}, label="Totally Different") as step:
        assert step.cached is True
        assert step.value == {"script": "hi"}
        if not step.cached:  # pragma: no cover - guard proves body is skippable
            ran.append(1)
            step.set({"script": "SHOULD NOT HAPPEN"})
    assert ran == []
    events = [e for e in _emitted_events(capsys) if e.get("t") == "step"]
    assert len(events) == 1
    assert events[0]["status"] == "cached"
    assert events[0]["name"] == "write-script"


def test_step_different_inputs_are_distinct_steps(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with ctx.step("gen", inputs={"n": 1}) as a:
        assert a.cached is False
        a.set({"r": 1})
    with ctx.step("gen", inputs={"n": 2}) as b:
        assert b.cached is False  # different inputs -> its own step, a miss
        b.set({"r": 2})
    ctx2 = _make_ctx(tmp_path)
    with ctx2.step("gen", inputs={"n": 1}) as a2:
        assert a2.cached is True
        assert a2.value == {"r": 1}


def test_step_version_bump_invalidates(tmp_path: Path) -> None:
    old = _make_ctx(tmp_path, version="1.0.0")
    with old.step("gen", inputs={"n": 1}) as s:
        s.set({"r": "old"})
    new = _make_ctx(tmp_path, version="1.0.1")
    with new.step("gen", inputs={"n": 1}) as s:
        assert s.cached is False  # a version bump must not return the old result


def test_step_stores_and_restores_returned_files_by_content(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    (ctx.artifacts / "final.mp4").write_bytes(b"FRAMES")
    with ctx.step("render", inputs={"shot": 1}) as step:
        step.set({"video": "final.mp4"})

    # Fresh run: artifacts empty, cache hit must restore the file into artifacts.
    ctx2 = _make_ctx(tmp_path)
    for leftover in ctx2.artifacts.iterdir():
        leftover.unlink()
    with ctx2.step("render", inputs={"shot": 1}) as step:
        assert step.cached is True
        assert step.value == {"video": "final.mp4"}
    assert (ctx2.artifacts / "final.mp4").read_bytes() == b"FRAMES"


def test_step_body_that_raises_is_not_cached(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with pytest.raises(RuntimeError, match="boom"), ctx.step("gen", inputs={"n": 1}) as step:
        assert step.cached is False
        raise RuntimeError("boom")
    # The failed step must not have been cached.
    ctx2 = _make_ctx(tmp_path)
    with ctx2.step("gen", inputs={"n": 1}) as step:
        assert step.cached is False
