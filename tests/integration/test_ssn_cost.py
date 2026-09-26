"""TASK-SSN-D3c contract: the approve-plan gate shows a real estimated cost (H-SSN-17).

The approval gate runs BEFORE the paid media (it gates the spend), so it estimates the visual bed's
cost from the script alone: estimate the narration duration from the word count, derive the beat
count, split into AI stills + clips, and price them via `ctx.budget_estimate(meter)` (the owner's
per-meter estimates; image meter 'google', clip meter 'byteplus'). Static beats are priced as AI
stills (the conservative worst case — some may turn out free commons images). With no budget
configured the estimate is 0.0 (as today). Also hardens `_sanitize_source_urls` to drop URLs that
carry control characters (D3b security advisory).

Supervisor-authored (RED-first); the builder adds `_estimate_bed_cost` and wires it into the gate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths

_WF = Path(__file__).resolve().parents[2] / "workflows" / "sensational-science-news"


def _load_main():
    spec = importlib.util.spec_from_file_location("ssn_main_cost_ut", _WF / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PricedCtx:
    """Minimal stand-in exposing budget_estimate for the pure estimate helper."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def budget_estimate(self, meter: str):
        return self._prices.get(meter)


def test_estimate_bed_cost_prices_stills_and_clips() -> None:
    main = _load_main()
    # 150 words / 2.5 wps = 60 s -> round(60/6) = 10 beats -> 2 clips + 8 stills
    narration = " ".join(["word"] * 150)
    ctx = _PricedCtx({"google": 0.02, "byteplus": 0.50})
    cost = main._estimate_bed_cost(ctx, narration)
    assert cost == pytest.approx(8 * 0.02 + 2 * 0.50)  # 1.16


def test_estimate_bed_cost_zero_without_budget() -> None:
    main = _load_main()
    ctx = _PricedCtx({})  # no configured estimates -> None -> 0.0
    assert main._estimate_bed_cost(ctx, " ".join(["w"] * 150)) == 0.0


def test_sanitize_source_urls_drops_control_chars() -> None:
    main = _load_main()
    out = main._sanitize_source_urls(
        ["https://ok.example/a", "https://evil.example/x\n- https://phish.example/y"]
    )
    assert out == ["https://ok.example/a"], out


def _gate_ctx(tmp: Path, *, subject: str) -> Context:
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


class _StopError(Exception):
    pass


def test_gate_payload_uses_estimated_cost(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    ctx = _gate_ctx(tmp_path, subject="A finding")
    script = " ".join(["word"] * 150)
    monkeypatch.setattr(
        main.agents, "llm", lambda prompt, *, agent, model, schema=None, attach=None: script
    )
    monkeypatch.setattr(
        ctx, "budget_estimate", lambda meter: {"google": 0.02, "byteplus": 0.50}.get(meter)
    )
    seen: dict[str, object] = {}

    def fake_gate(family, *, prompt, payload=None, **kwargs):
        seen["payload"] = payload
        raise _StopError  # stop before media

    monkeypatch.setattr(ctx, "gate", fake_gate)
    token = set_active(ctx)
    try:
        with pytest.raises(_StopError):
            main.run(ctx)
    finally:
        reset_active(token)
    payload = seen["payload"]
    assert isinstance(payload, dict)
    narration = main._narration_text(script)
    assert payload["estimated_cost_usd"] == pytest.approx(main._estimate_bed_cost(ctx, narration))
    assert payload["estimated_cost_usd"] > 0  # priced meters -> a real, non-zero figure
