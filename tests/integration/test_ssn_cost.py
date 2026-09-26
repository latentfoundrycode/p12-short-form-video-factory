"""TASK-SSN-D-fix contract: the approve-plan gate estimates the REAL reserve (Review B blocker).

A paid render reserves max(adapter price, owner estimate), not just the owner's configured figure —
so `_estimate_bed_cost` prices stills/clips at max(media.{image,video}.price(...), budget_estimate),
plus a per-static-beat vision allowance for the commons relevance check, so the gate never shows a
figure far below what the run will spend. With no budget configured the estimate is still non-zero
(the adapter prices apply). Also hardens `_sanitize_source_urls` (control chars, missing host,
userinfo).

Supervisor-authored (RED-first); the builder reworks `_estimate_bed_cost` + `_sanitize_source_urls`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sfvf import media
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
    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = prices

    def budget_estimate(self, meter: str):
        return self._prices.get(meter)


def _expected(main, ctx, narration: str) -> float:
    words = len(narration.split())
    beats = max(1, round((words / main._WORDS_PER_SEC) / main._BEAT_S))
    clips = min(main._MAX_CLIPS, 2 if beats >= 4 else 1)
    statics = max(0, beats - clips)
    still_unit = max(
        media.image.price(main._IMAGE_MODEL), ctx.budget_estimate(main._IMAGE_METER) or 0.0
    )
    clip_unit = max(
        media.video.price(main._CLIP_MODEL, main._CLIP_DURATION_S),
        ctx.budget_estimate(main._CLIP_METER) or 0.0,
    )
    return round(clips * clip_unit + statics * (still_unit + main._RELEVANCE_COST_USD), 2)


def test_estimate_bed_cost_uses_adapter_price_when_configured_is_lower() -> None:
    main = _load_main()
    ctx = _PricedCtx({"google": 0.001, "byteplus": 0.001})  # far below the real adapter prices
    narration = " ".join(["word"] * 150)  # ~60s -> 10 beats -> 2 clips + 8 stills
    cost = main._estimate_bed_cost(ctx, narration)
    assert cost == pytest.approx(_expected(main, ctx, narration))
    # the adapter clip price (~$2.7 for 5s Seedance) dominates the owner's tiny 0.001 estimate
    assert cost > 5.0, f"estimate must reflect the real reserve, got {cost}"


def test_estimate_bed_cost_uses_configured_when_higher() -> None:
    main = _load_main()
    ctx = _PricedCtx({"google": 100.0, "byteplus": 200.0})  # above adapter -> configured wins
    narration = " ".join(["word"] * 150)
    assert main._estimate_bed_cost(ctx, narration) == pytest.approx(_expected(main, ctx, narration))


def test_estimate_bed_cost_nonzero_without_budget() -> None:
    main = _load_main()
    ctx = _PricedCtx({})  # no configured estimates -> adapter prices still apply
    assert main._estimate_bed_cost(ctx, " ".join(["w"] * 150)) > 0.0


def test_sanitize_source_urls_drops_control_chars_hosts_and_userinfo() -> None:
    main = _load_main()
    out = main._sanitize_source_urls(
        [
            "https://ok.example/a",
            "https://evil.example/x\n- https://phish.example/y",  # control char
            "https:javascript:alert(1)",  # no host
            "http://user:pass@host.example/p",  # userinfo
            "http://plainhost.example/b",
        ]
    )
    assert out == ["https://ok.example/a", "http://plainhost.example/b"], out


class _StopError(Exception):
    pass


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


def test_gate_payload_uses_estimated_cost(tmp_path: Path, monkeypatch) -> None:
    main = _load_main()
    ctx = _gate_ctx(tmp_path, subject="A finding")
    script = " ".join(["word"] * 150)
    monkeypatch.setattr(
        main.agents, "llm", lambda prompt, *, agent, model, schema=None, attach=None: script
    )
    seen: dict[str, object] = {}

    def fake_gate(family, *, prompt, payload=None, **kwargs):
        seen["payload"] = payload
        raise _StopError

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
    assert payload["estimated_cost_usd"] > 0  # a real, non-zero figure from the adapter prices
