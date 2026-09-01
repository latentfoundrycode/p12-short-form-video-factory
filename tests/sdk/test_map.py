"""Reviewer-authored contract for `ctx.map` (SDK-3) — many steps of one family, in parallel.

Workflow SDK §4.7: every item is a full step (own cache key, own record entry); results come
back in INPUT order whatever order they finished; `on_error="raise"` (default) propagates the
first failure, `on_error="collect"` returns an outcome per item; work runs up to `concurrency` at
once. Concurrency also means concurrent `step` events on stdout — they must not interleave.
"""

import json
import threading
import time
from pathlib import Path

import pytest
from sfvf.context import Context, ContextFile, ContextPaths


def _make_ctx(tmp_path: Path, *, version: str = "1.0.0") -> Context:
    video = tmp_path / "01"
    artifacts = video / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (video / ".steps").mkdir(parents=True, exist_ok=True)
    shared = tmp_path / "shared"
    shared.mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            paths=ContextPaths(
                video=video,
                artifacts=artifacts,
                steps=video / ".steps",
                shared=shared,
                cache=tmp_path / "cache",
            ),
            workflow_version=version,
        )
    )


def test_map_returns_results_in_input_order(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    items = [1, 2, 3, 4]

    def fn(n: int) -> dict:
        time.sleep(0.02 * (5 - n))  # later items finish first
        return {"n": n, "sq": n * n}

    results = ctx.map(
        "square", items, inputs=lambda n: {"n": n}, fn=fn, concurrency=4, on_error="raise"
    )
    assert results == [{"n": 1, "sq": 1}, {"n": 2, "sq": 4}, {"n": 3, "sq": 9}, {"n": 4, "sq": 16}]


def test_map_items_are_cached_per_item(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    items = [1, 2, 3]
    calls: list[int] = []

    def fn(n: int) -> dict:
        calls.append(n)
        return {"n": n}

    first = ctx.map("gen", items, inputs=lambda n: {"n": n}, fn=fn, concurrency=2)
    assert first == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert sorted(calls) == [1, 2, 3]

    calls.clear()
    ctx2 = _make_ctx(tmp_path)  # same cache root
    second = ctx2.map("gen", items, inputs=lambda n: {"n": n}, fn=fn, concurrency=2)
    assert second == [{"n": 1}, {"n": 2}, {"n": 3}]
    assert calls == []  # every item was a cache hit; fn not called


def test_map_on_error_raise_propagates(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)

    def fn(n: int) -> dict:
        if n == 2:
            raise RuntimeError("boom on 2")
        return {"n": n}

    with pytest.raises(RuntimeError, match="boom on 2"):
        ctx.map("gen", [1, 2, 3], inputs=lambda n: {"n": n}, fn=fn, concurrency=1, on_error="raise")


def test_map_on_error_collect_returns_outcome_per_item(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)

    def fn(n: int) -> dict:
        if n == 2:
            raise RuntimeError("boom on 2")
        return {"n": n}

    outcomes = ctx.map(
        "gen", [1, 2, 3], inputs=lambda n: {"n": n}, fn=fn, concurrency=3, on_error="collect"
    )
    assert len(outcomes) == 3
    assert outcomes[0].ok and outcomes[0].value == {"n": 1}
    assert outcomes[2].ok and outcomes[2].value == {"n": 3}
    assert not outcomes[1].ok
    assert isinstance(outcomes[1].error, Exception)
    assert "boom on 2" in str(outcomes[1].error)


def test_map_collect_collects_exceptions_but_propagates_base_exceptions(tmp_path: Path) -> None:
    """`on_error="collect"` collects ordinary Exceptions into Outcomes, but a process-control
    BaseException (SystemExit/KeyboardInterrupt and the like) must propagate, not be swallowed."""

    class Fatal(BaseException):
        pass

    ctx = _make_ctx(tmp_path)

    def fn(n: int) -> dict:
        if n == 2:
            raise Fatal("fatal")
        return {"n": n}

    with pytest.raises(Fatal):
        ctx.map(
            "gen", [1, 2, 3], inputs=lambda n: {"n": n}, fn=fn, concurrency=1, on_error="collect"
        )


def test_map_runs_items_concurrently_up_to_concurrency(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    barrier = threading.Barrier(3, timeout=5)  # only clears if 3 items run at once

    def fn(n: int) -> dict:
        barrier.wait()  # deterministic proof of >=3-way parallelism
        return {"n": n}

    results = ctx.map(
        "gen", [1, 2, 3], inputs=lambda n: {"n": n}, fn=fn, concurrency=3, on_error="raise"
    )
    assert results == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_map_concurrent_step_events_do_not_interleave(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ctx = _make_ctx(tmp_path)
    ctx.map("gen", list(range(12)), inputs=lambda n: {"n": n}, fn=lambda n: {"n": n}, concurrency=6)
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    step_events = 0
    for line in lines:
        event = json.loads(line)  # every emitted line must be a complete, valid JSON object
        if event.get("t") == "step":
            step_events += 1
    assert step_events == 12  # one step event per item, none lost or torn
