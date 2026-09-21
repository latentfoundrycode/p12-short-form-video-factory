"""Frozen contract — web-image-sourcing increment 4: `media.web.check_relevance` (the VLM gate).

`check_relevance(image, *, subject, model=_VISION_MODEL) -> Relevance` shows a downloaded+normalised
image to a vision model (via `agents.llm(attach=[image], schema=...)`, i.e. agents.vision, PR #139)
and returns `{relevant: bool, score: float in [0,1], reason: str}` — the SFVF-provided assessment of
whether the image actually depicts the workflow's `subject`. Dry-run returns a passing stub and must
NOT call the model (design §3.2). The real path is exercised against a MOCKED `agents.llm` — no
network, no real vision model.
"""

from pathlib import Path

import pytest
from sfvf import agents, media
from sfvf._runtime import reset_active, set_active
from sfvf.context import Context, ContextFile, ContextPaths
from sfvf.media import web as web_mod


def _ctx(tmp: Path, *, dry_run: bool) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
        )
    )


def _run(ctx: Context, fn):
    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _install_llm(monkeypatch: pytest.MonkeyPatch, returns) -> list[dict]:
    """Patch agents.llm; record each call's kwargs; return `returns` (dict or callable)."""
    calls: list[dict] = []

    def fake_llm(prompt, *, agent, model, schema=None, attach=None):
        calls.append(
            {"prompt": prompt, "agent": agent, "model": model, "schema": schema, "attach": attach}
        )
        return returns(calls) if callable(returns) else returns

    monkeypatch.setattr(agents, "llm", fake_llm)
    return calls


# --- dry-run: passing stub, no model call ------------------------------------------------------


def test_check_relevance_dry_run_returns_a_passing_stub_without_calling_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_llm(monkeypatch, {"relevant": False, "score": 0.0, "reason": "should not run"})
    out = _run(
        _ctx(tmp_path, dry_run=True),
        lambda: media.web.check_relevance("shot.png", subject="a red barn"),
    )
    assert out == {"relevant": True, "score": 1.0, "reason": "dry-run stub"}
    assert calls == [], "dry-run must NOT call the vision model"


# --- real path: agents.vision call shape + verdict mapping -------------------------------------


def test_check_relevance_real_calls_agents_vision_with_the_image_and_a_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_llm(
        monkeypatch, {"relevant": True, "score": 0.82, "reason": "a red barn is clearly visible"}
    )
    out = _run(
        _ctx(tmp_path, dry_run=False),
        lambda: media.web.check_relevance("web-abc.png", subject="a red barn in a field"),
    )
    assert out["relevant"] is True
    assert out["score"] == pytest.approx(0.82)
    assert out["reason"] == "a red barn is clearly visible"
    assert len(calls) == 1
    c = calls[0]
    # the image is attached (agents.vision), and only that image
    assert c["attach"] == ["web-abc.png"]
    # a structured verdict is requested via json schema for {relevant, score, reason}
    assert isinstance(c["schema"], dict)
    props = c["schema"].get("properties", {})
    assert {"relevant", "score", "reason"} <= set(props)
    # the subject is put to the model
    assert "a red barn in a field" in c["prompt"]
    assert isinstance(c["agent"], str) and c["agent"]
    # default model is the vision model
    assert c["model"] == web_mod._VISION_MODEL


def test_check_relevance_forwards_an_overridden_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_llm(monkeypatch, {"relevant": True, "score": 0.7, "reason": "ok"})
    _run(
        _ctx(tmp_path, dry_run=False),
        lambda: media.web.check_relevance("x.png", subject="s", model="anthropic/claude-vision"),
    )
    assert calls[0]["model"] == "anthropic/claude-vision"


def test_check_relevance_rejects_an_irrelevant_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_llm(monkeypatch, {"relevant": False, "score": 0.1, "reason": "a blue car, not a barn"})
    out = _run(
        _ctx(tmp_path, dry_run=False),
        lambda: media.web.check_relevance("x.png", subject="a red barn"),
    )
    assert out["relevant"] is False
    assert out["score"] == pytest.approx(0.1)
    assert out["reason"] == "a blue car, not a barn"


# --- robustness: coerce/clamp the untrusted model output ---------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [(1.5, 1.0), (-0.3, 0.0), (2, 1.0), (0.5, 0.5), (0, 0.0), (1, 1.0)],
)
def test_check_relevance_clamps_score_to_unit_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw, expected
) -> None:
    # the model output is untrusted; a score outside [0,1] must be clamped, not passed through
    _install_llm(monkeypatch, {"relevant": True, "score": raw, "reason": "r"})
    out = _run(
        _ctx(tmp_path, dry_run=False),
        lambda: media.web.check_relevance("x.png", subject="s"),
    )
    assert out["score"] == pytest.approx(expected)
    assert isinstance(out["score"], float)


def test_check_relevance_coerces_verdict_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # relevant -> bool, reason -> str, regardless of the model's exact JSON types
    _install_llm(monkeypatch, {"relevant": 1, "score": 0.9, "reason": 42})
    out = _run(
        _ctx(tmp_path, dry_run=False),
        lambda: media.web.check_relevance("x.png", subject="s"),
    )
    assert out["relevant"] is True
    assert isinstance(out["reason"], str)
