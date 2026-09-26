"""TASK-SSN-C4 contract: run() gates the plan for approval before spending on media.

After the (cheap) script is written, run() must call ctx.gate("approve-plan", ...) with a payload
owner can judge -- the subject, the narration script, and an estimated cost -- BEFORE the expensive
media steps (speech / render / finalize). On approval it proceeds; on rejection ctx.gate raises
GateRejected, which ends THIS video (the chassis runner marks it and lets sibling videos continue).
A scheduled run sets gates_auto, and the gate is declared on_bypass="approve" so it auto-approves
without a human -- that bypass is SDK behaviour (tests/sdk/test_gate.py), so here we pin the
WORKFLOW contract: the call is made, with the right family/payload, at the right point (after the
script, before media). We patch ctx.gate to observe the call without the gate wire protocol.

Supervisor-authored (RED-first); the builder adds the ctx.gate call to run().
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.gate import GateRejected

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_gate_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ctx(tmp: Path, *, subject: str) -> Context:
    (tmp / "01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp / "01" / ".steps").mkdir(parents=True, exist_ok=True)
    (tmp / "cache").mkdir(parents=True, exist_ok=True)
    return Context(
        ContextFile(
            settings={},
            dry_run=True,
            workflow_id="sensational-science-news",
            video_index=1,
            video_count=1,
            voice="",
            shared={"subjects": [subject], "sources": {subject: []}},
            paths=ContextPaths(
                video=tmp / "01",
                artifacts=tmp / "01" / "artifacts",
                steps=tmp / "01" / ".steps",
                shared=tmp / "01",
                cache=tmp / "cache",
                library=tmp / "lib",
            ),
        )
    )


class _MediaReachedError(Exception):
    pass


def _patch_script_llm(monkeypatch, main, script: str) -> None:
    monkeypatch.setattr(
        main.agents,
        "llm",
        lambda prompt, *, agent, model, schema=None, attach=None: script,
    )


def test_run_gates_plan_after_script_before_media(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    subject = "Gut bacteria linked to memory"
    _patch_script_llm(monkeypatch, main, "Amazing discovery about gut bacteria and the brain.")
    ctx = _ctx(tmp_path, subject=subject)

    seen: dict[str, object] = {}

    def fake_gate(family, *, prompt, payload=None, **kwargs):
        seen["family"] = family
        seen["payload"] = payload
        return {"choice": "approve"}

    # if speech is reached, record that it happened AFTER the gate (order check)
    def guard_speak(*args, **kwargs):
        seen["media_reached_with_gate"] = "family" in seen
        raise _MediaReachedError

    monkeypatch.setattr(ctx, "gate", fake_gate)
    monkeypatch.setattr(main.media.speech, "speak", guard_speak)

    token = set_active(ctx)
    try:
        with pytest.raises(_MediaReachedError):
            main.run(ctx)
    finally:
        reset_active(token)

    assert seen.get("family") == "approve-plan"
    payload = seen.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("subject") == subject
    assert isinstance(payload.get("script"), str) and payload["script"].strip()
    assert (
        "gut bacteria" in payload["script"].lower()
    )  # the generated script -> gate is post-script
    # a cost figure the owner can judge before approving the spend
    cost = payload.get("estimated_cost_usd")
    assert isinstance(cost, int | float) and not isinstance(cost, bool)
    assert seen.get("media_reached_with_gate") is True  # media ran only after the gate


def test_run_gate_reject_aborts_before_media(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    subject = "A real finding"
    _patch_script_llm(monkeypatch, main, "A gripping narration.")
    ctx = _ctx(tmp_path, subject=subject)

    def reject_gate(family, *, prompt, payload=None, **kwargs):
        raise GateRejected("owner declined")

    reached = {"speak": False}

    def guard_speak(*args, **kwargs):
        reached["speak"] = True
        raise _MediaReachedError  # fail fast if reached; a correct run() rejects before any media

    monkeypatch.setattr(ctx, "gate", reject_gate)
    monkeypatch.setattr(main.media.speech, "speak", guard_speak)

    token = set_active(ctx)
    try:
        with pytest.raises(GateRejected):
            main.run(ctx)
    finally:
        reset_active(token)

    assert reached["speak"] is False  # rejecting the plan spends nothing on media
