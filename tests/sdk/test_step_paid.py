"""C-6 contract: `ctx.step(paid=...)` selects the cache partition (§5.9).

A paid step's result goes to the paid partition (never auto-evicted); an ordinary step's result
goes to the cheap partition (LRU-evicted). The flag defaults to cheap.
"""

from __future__ import annotations

from pathlib import Path

from sfvf.cache import StepCache, step_key
from sfvf.context import Context, ContextFile, ContextPaths

_VERSION = "1.0.0"


def _make_ctx(tmp_path: Path) -> Context:
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
            workflow_version=_VERSION,
        )
    )


def test_paid_step_routes_to_the_paid_partition(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with ctx.step("gen", inputs={"x": 1}, paid=True) as step:
        if not step.cached:
            step.set({"ok": True})
    root = tmp_path / "cache"
    key = step_key(_VERSION, "gen", {"x": 1})
    assert StepCache(root, partition="paid").get(key) == {"ok": True}
    assert StepCache(root, partition="cheap").get(key) is None


def test_default_step_routes_to_the_cheap_partition(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with ctx.step("render", inputs={"x": 2}) as step:
        if not step.cached:
            step.set({"ok": True})
    root = tmp_path / "cache"
    key = step_key(_VERSION, "render", {"x": 2})
    assert StepCache(root, partition="cheap").get(key) == {"ok": True}
    assert StepCache(root, partition="paid").get(key) is None


def test_paid_step_is_read_back_from_the_paid_partition_on_a_hit(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with ctx.step("gen", inputs={"x": 1}, paid=True) as first:
        if not first.cached:
            first.set({"n": 7})
    # A second paid step with the same inputs must hit the paid partition, not re-run the body.
    with ctx.step("gen", inputs={"x": 1}, paid=True) as second:
        assert second.cached is True
        assert second.value == {"n": 7}
