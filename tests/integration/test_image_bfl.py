"""Frozen contract — Stage P, P-6: the Black Forest Labs (Flux) image adapter.

BFL sits behind the same media.image surface as OpenAI, but its lifecycle is ASYNCHRONOUS and its
auth is a custom header: submit `POST /v1/<slug>` with `x-key: <BFL_API_KEY>` -> {id, polling_url};
poll `GET /v1/get_result?id=<id>` until status "Ready"; the image is a signed URL at
`result.sample`, which is downloaded. The adapter hides the poll behind the image-adapter interface
(generate/edit -> Output), so no surface change is needed. Two models: `bfl/flux-1.1-pro`
(text-to-image, `/v1/flux-pro-1.1`, width/height) generates; `bfl/flux-kontext-pro`
(`/v1/flux-kontext-pro`, `input_image`) edits with a reference image. Cost is priced per image
(pinned credits, source "priced") for this first cut.

All HTTP is exercised against httpx2.MockTransport by monkeypatching `sfvf.providers.bfl._client`
(+ `_POLL_INTERVAL_S`). No live network, an in-memory fake key.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import CapabilityError, capabilities_offered, resolve

_KEY = "bfl-fake-key-not-real"
_MODEL_GEN = "bfl/flux-1.1-pro"
_SLUG_GEN = "flux-pro-1.1"
_MODEL_EDIT = "bfl/flux-kontext-pro"
_SLUG_EDIT = "flux-kontext-pro"
_PNG = b"\x89PNG\r\n\x1a\nFAKE-BFL-IMAGE"
_SAMPLE_URL = "https://bfl-cdn.example.test/result/img.png"


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"BFL_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"bfl": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _ready_handler(polls_before_ready: int = 1):
    """submit -> {id, polling_url}; get_result Pending N times then Ready; sample URL -> bytes."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST" and path.startswith("/v1/flux"):
            return httpx2.Response(
                200,
                json={
                    "id": "bfl-123",
                    "polling_url": "https://api.bfl.ai/v1/get_result?id=bfl-123",
                    "cost": 4.0,
                },
            )
        if request.method == "GET" and path == "/v1/get_result":
            n = sum(1 for r in seen if r.method == "GET" and r.url.path == "/v1/get_result")
            if n <= polls_before_ready:
                return httpx2.Response(200, json={"id": "bfl-123", "status": "Pending"})
            return httpx2.Response(
                200,
                json={
                    "id": "bfl-123",
                    "status": "Ready",
                    "result": {"sample": _SAMPLE_URL},
                    "cost": 4.0,
                },
            )
        if request.method == "GET" and path == "/result/img.png":
            return httpx2.Response(200, content=_PNG)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=httpx2.MockTransport(wrapped))

    from sfvf.providers import bfl as bfl_adapter

    monkeypatch.setattr(bfl_adapter, "_client", _client)
    monkeypatch.setattr(bfl_adapter, "_POLL_INTERVAL_S", 0.0)
    return seen


def _run(ctx: Context, fn):
    from sfvf._runtime import reset_active, set_active

    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _cost_events(captured: str) -> list[dict]:
    events = []
    for line in captured.splitlines():
        s = line.strip()
        if s.startswith("{"):
            try:
                obj = json.loads(s)
            except ValueError:
                continue
            if obj.get("t") == "cost":
                events.append(obj)
    return events


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_bfl_models_registered() -> None:
    gp, gm = resolve(_MODEL_GEN)
    assert gp.id == "bfl" and gm.kind == "image" and gm.slug == _SLUG_GEN
    assert "image.generate" in gm.capabilities
    ep, em = resolve(_MODEL_EDIT)
    assert em.slug == _SLUG_EDIT and "image.edit" in em.capabilities
    assert "image.generate" in capabilities_offered({"BFL_API_KEY"})
    assert capabilities_offered(
        set()
    ) == frozenset() or "image.generate" not in capabilities_offered(set())


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run must not hit the network")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.image.generate("a fox", model=_MODEL_GEN))
    assert (tmp_path / out).is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real generate — x-key, submit /v1/flux-pro-1.1, poll get_result, download sample
# ---------------------------------------------------------------------------


def test_generate_real_uses_x_key_polls_and_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ready_handler(polls_before_ready=1))
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(
        ctx, lambda: media.image.generate("a red fox in snow", model=_MODEL_GEN, size="1024x768")
    )
    assert (tmp_path / out).read_bytes() == _PNG

    submit = seen[0]
    assert submit.method == "POST" and submit.url.path == f"/v1/{_SLUG_GEN}"
    assert submit.headers.get("x-key") == _KEY
    assert submit.headers.get("authorization") is None  # NOT Bearer
    body = json.loads(submit.read())
    assert body["prompt"] == "a red fox in snow"
    assert body["width"] == 1024 and body["height"] == 768
    assert any(r.method == "GET" and r.url.path == "/v1/get_result" for r in seen)
    assert any(r.method == "GET" and r.url.path == "/result/img.png" for r in seen)


def test_generate_real_records_a_priced_cost_in_credits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _ready_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.image.generate("a fox", model=_MODEL_GEN))
    events = _cost_events(capsys.readouterr().out)
    assert events
    event = events[-1]
    assert event["meter"] == "bfl" and event["unit"] == "credits"
    assert event["source"] == "priced" and event["amount"] > 0


# ---------------------------------------------------------------------------
# Real edit — /v1/flux-kontext-pro with input_image
# ---------------------------------------------------------------------------


def test_edit_real_sends_input_image_to_kontext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ready_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "src.png").write_bytes(_PNG)

    out = _run(
        ctx, lambda: media.image.edit("artifacts/src.png", "make it night", model=_MODEL_EDIT)
    )
    assert (tmp_path / out).is_file()

    submit = seen[0]
    assert submit.method == "POST" and submit.url.path == f"/v1/{_SLUG_EDIT}"
    assert submit.headers.get("x-key") == _KEY
    body = json.loads(submit.read())
    assert body["prompt"] == "make it night"
    # the source image is sent as base64 in input_image
    assert body["input_image"] == base64.b64encode(_PNG).decode()


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_generate_on_an_edit_only_model_raises_capability_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ready_handler())
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(CapabilityError):
        _run(
            ctx, lambda: media.image.generate("x", model=_MODEL_EDIT)
        )  # kontext is image.edit only
    assert seen == []


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _ready_handler())
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.image.generate("x", model=_MODEL_GEN))
    assert seen == []
