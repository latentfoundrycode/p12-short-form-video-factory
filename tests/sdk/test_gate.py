"""H-1 contract: `ctx.gate()` — the interactive approval gate (Architecture §3.5, SDK guide §4.6).

A workflow calls `ctx.gate(...)` to pause before an expensive stage; it emits a `gate` event and
BLOCKS until a response file appears in the video folder, then returns the decision. Three shapes:

    Approval   prompt[, payload]                   -> {"choice": "approve"|"reject"}
    Choice     options=[...]                        -> {"choice": "<option>"}
    Selection  items=[...], select="subset"         -> {"choice","keep":[ids],"redo":[ids],"note"}

`{"choice":"reject"}` raises `GateRejected`. A scheduled run may set the injected `gates_auto` flag,
in which case the gate returns `on_bypass` WITHOUT blocking (writing it so the record/resume see
it); `on_bypass` is mandatory for any shape that can return more than plain approval. Response files
persist in `video/gates/<token>.json` where `<token>` is deterministic per (family, occurrence), so
a resumed run re-reads the earlier decision instead of re-prompting. `ctx.gate_attempts(family,
item=...)` counts how many times that item was sent back to redo, derived from those recorded
decisions, so a redo loop can vary its cache key and not re-serve the cached original.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.gate import GateRejected


def _ctx(video_dir: Path, *, gates_auto: bool = False) -> Context:
    return Context(
        ContextFile(
            settings={},
            gates_auto=gates_auto,
            paths=ContextPaths(
                video=video_dir,
                artifacts=video_dir / "artifacts",
                steps=video_dir / ".steps",
                shared=video_dir,
            ),
        )
    )


def _write_response(video_dir: Path, token: str, decision: dict[str, Any]) -> None:
    path = video_dir / "gates" / f"{token}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision), encoding="utf-8")


def test_gate_returns_existing_response_without_blocking(tmp_path: Path) -> None:
    # Resume / already-answered: a response file present up front is read and returned immediately.
    video = tmp_path / "01"
    video.mkdir()
    _write_response(video, "approve-script-0", {"choice": "approve"})
    ctx = _ctx(video)
    assert ctx.gate("approve-script", prompt="ok?") == {"choice": "approve"}


def test_gate_emits_event_then_blocks_until_response(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video)
    result: dict[str, Any] = {}

    def run() -> None:
        result["decision"] = ctx.gate("approve-script", prompt="Approve?", payload={"script": "hi"})

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.1)
    assert worker.is_alive()  # still blocking, no response yet
    _write_response(video, "approve-script-0", {"choice": "approve"})
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert result["decision"] == {"choice": "approve"}
    # a `gate` event was emitted carrying the family, a token, the shape and the prompt
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    gate_events = [e for e in events if e.get("t") == "gate"]
    assert len(gate_events) == 1
    assert gate_events[0]["family"] == "approve-script"
    assert gate_events[0]["shape"] == "approval"
    assert gate_events[0]["token"] == "approve-script-0"


def test_gate_reject_raises(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    _write_response(video, "approve-script-0", {"choice": "reject", "note": "no good"})
    ctx = _ctx(video)
    with pytest.raises(GateRejected):
        ctx.gate("approve-script", prompt="ok?")


def test_choice_shape_returns_chosen_option(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    _write_response(video, "pick-tone-0", {"choice": "warm"})
    ctx = _ctx(video)
    got = ctx.gate("pick-tone", prompt="tone?", options=["warm", "cool"], on_bypass="warm")
    assert got == {"choice": "warm"}


def test_choice_without_on_bypass_is_authoring_error_even_interactive(tmp_path: Path) -> None:
    # on_bypass is mandatory for any gate that can return more than plain approval, and the check
    # fires at the call (not only under gates_auto) so a schedule-time break is caught early.
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video)  # interactive (gates_auto False)
    with pytest.raises(ValueError):
        ctx.gate("pick-tone", prompt="tone?", options=["warm", "cool"])


def test_choice_invalid_on_bypass_is_error(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video)
    with pytest.raises(ValueError):
        ctx.gate("pick-tone", prompt="tone?", options=["warm", "cool"], on_bypass="bogus")


def test_selection_shape_returns_keep_and_redo(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    _write_response(
        video,
        "approve-sheets-0",
        {"choice": "approve", "keep": ["bertie"], "redo": ["clementine"], "note": "hood"},
    )
    ctx = _ctx(video)
    decision = ctx.gate(
        "approve-sheets",
        prompt="Approve the sheets.",
        items=[
            {"id": "bertie", "artifact": "artifacts/bertie.png"},
            {"id": "clementine", "artifact": "artifacts/clementine.png"},
        ],
        select="subset",
        on_bypass="approve-all",
    )
    assert decision["keep"] == ["bertie"] and decision["redo"] == ["clementine"]


def test_token_increments_per_family_occurrence(tmp_path: Path) -> None:
    # Two gates of the SAME family in one video get distinct, deterministic tokens (…-0, …-1),
    # so a redo loop's second prompt is not answered by the first one's response file.
    video = tmp_path / "01"
    video.mkdir()
    _write_response(video, "approve-sheets-0", {"choice": "approve", "keep": [], "redo": ["c"]})
    _write_response(video, "approve-sheets-1", {"choice": "approve", "keep": ["c"], "redo": []})
    ctx = _ctx(video)
    first = ctx.gate(
        "approve-sheets", prompt="p", items=[{"id": "c"}], select="subset", on_bypass="approve-all"
    )
    second = ctx.gate(
        "approve-sheets", prompt="p", items=[{"id": "c"}], select="subset", on_bypass="approve-all"
    )
    assert first["redo"] == ["c"] and second["keep"] == ["c"]


def test_bypass_returns_on_bypass_without_blocking(tmp_path: Path) -> None:
    # gates_auto (scheduled run, nobody present): the gate resolves immediately from on_bypass and
    # persists the decision so the record/resume can see it — no event-wait.
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video, gates_auto=True)
    decision = ctx.gate(
        "approve-sheets",
        prompt="p",
        items=[{"id": "bertie"}, {"id": "clementine"}],
        select="subset",
        on_bypass="approve-all",
    )
    assert decision["choice"] == "approve"
    assert set(decision["keep"]) == {"bertie", "clementine"} and decision["redo"] == []
    # persisted for the record / a later resume
    assert (video / "gates" / "approve-sheets-0.json").is_file()


def test_bypass_plain_approval_defaults_to_approve(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video, gates_auto=True)
    assert ctx.gate("approve-script", prompt="ok?") == {"choice": "approve"}


def test_bypass_missing_on_bypass_for_richer_shape_is_authoring_error(tmp_path: Path) -> None:
    # §3.5: the chassis never invents a default for a gate that can return more than approval.
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video, gates_auto=True)
    with pytest.raises(ValueError):
        ctx.gate("pick-tone", prompt="tone?", options=["warm", "cool"])  # no on_bypass


def test_gate_stops_when_stop_sentinel_appears(tmp_path: Path) -> None:
    # A graceful stop while parked at a gate must not hang: the `.stop` sentinel breaks the wait.
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video)
    error: dict[str, BaseException] = {}

    def run() -> None:
        try:
            ctx.gate("approve-script", prompt="ok?")
        except BaseException as exc:  # capture whatever the stop raises
            error["exc"] = exc

    worker = threading.Thread(target=run)
    worker.start()
    time.sleep(0.1)
    (video / ".stop").touch()
    worker.join(timeout=5)
    assert not worker.is_alive()  # the gate returned/raised rather than hanging
    assert "exc" in error


def test_gate_attempts_counts_redos_for_an_item(tmp_path: Path) -> None:
    video = tmp_path / "01"
    video.mkdir()
    ctx = _ctx(video)
    assert ctx.gate_attempts("approve-sheets", item="clementine") == 0
    _write_response(
        video,
        "approve-sheets-0",
        {"choice": "approve", "keep": ["bertie"], "redo": ["clementine"]},
    )
    assert ctx.gate_attempts("approve-sheets", item="clementine") == 1
    assert ctx.gate_attempts("approve-sheets", item="bertie") == 0


def test_gate_attempts_matches_family_exactly(tmp_path: Path) -> None:
    # A shorter family must NOT match a longer one's files: gate_attempts("approve") must not count
    # "approve-sheets-*.json", or it would silently perturb another step's cache key.
    video = tmp_path / "01"
    video.mkdir()
    _write_response(video, "approve-sheets-0", {"choice": "approve", "redo": ["clementine"]})
    _write_response(video, "approve-0", {"choice": "reject"})
    ctx = _ctx(video)
    assert ctx.gate_attempts("approve") == 1  # only approve-0, not approve-sheets-0
    assert ctx.gate_attempts("approve-sheets") == 1  # only approve-sheets-0
