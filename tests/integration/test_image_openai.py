"""Frozen contract — Stage P, P-3: the media.image surface + the OpenAI image adapter.

The provider-agnostic still-image surface (SDK §6.2) and the first real adapter behind it. OpenAI
image generation is SYNCHRONOUS: POST /v1/images/generations (JSON) or /v1/images/edits (multipart,
one or more `image[]` files) with `Authorization: Bearer <OPENAI_API_KEY>`, returning base64 image
data; the surface decodes it, writes an artifact, and records the cost (priced per image — a pinned,
dated per-image figure, source "priced"). dry_run is a genuine no-network stub (a solid placeholder
image, no key, no HTTP, no spend).

All HTTP is exercised against httpx2.MockTransport by monkeypatching `sfvf.providers.openai._client`
— no live network, an in-memory fake key. The model id `openai/gpt-image-2` is registered by this
increment (its adapter now exists, so per the seeding rule it may carry capabilities).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx2
import pytest
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import PROVIDERS, CapabilityError, capabilities_offered, resolve

_KEY = "sk-fake-openai-key-not-real"
_MODEL = "openai/gpt-image-2"
_PNG = b"\x89PNG\r\n\x1a\nFAKE-IMAGE-BYTES"
_B64 = base64.b64encode(_PNG).decode()


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"OPENAI_API_KEY": _KEY} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"openai": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request)

    def _client(base_url: str) -> httpx2.Client:
        return httpx2.Client(base_url=base_url, transport=httpx2.MockTransport(wrapped))

    from sfvf.providers import openai as openai_adapter

    monkeypatch.setattr(openai_adapter, "_client", _client)
    return seen


def _image_ok(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, json={"data": [{"b64_json": _B64}], "usage": {"total_tokens": 1}})


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
# Registry: the model is registered with its capabilities now that the adapter exists.
# ---------------------------------------------------------------------------


def test_openai_image_model_is_registered_with_image_capabilities() -> None:
    provider, model = resolve(_MODEL)
    assert provider.id == "openai" and model.kind == "image"
    assert {"image.generate", "image.edit"} <= model.capabilities
    assert {"image.generate", "image.edit"} <= capabilities_offered({"OPENAI_API_KEY"})
    # Not offered when the key is absent.
    assert "image.generate" not in capabilities_offered(set())


# ---------------------------------------------------------------------------
# Dry run — no network, no key, a real placeholder image.
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call_and_returns_a_stub_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_request: httpx2.Request) -> httpx2.Response:
        raise AssertionError("dry_run image generation must not make any network call")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.image.generate("a teal fox", model=_MODEL))

    assert isinstance(out, str) and not Path(out).is_absolute()
    assert (tmp_path / out).is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real generate — sync, Bearer, /v1/images/generations, b64 decoded, cost recorded.
# ---------------------------------------------------------------------------


def test_generate_real_posts_bearer_and_saves_the_decoded_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _image_ok)
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: media.image.generate("a teal fox", model=_MODEL, size="1024x1024"))

    saved = tmp_path / out
    assert saved.is_file() and saved.read_bytes() == _PNG  # base64 decoded and written

    submit = seen[0]
    assert submit.method == "POST"
    assert submit.url.path == "/v1/images/generations"
    assert submit.headers.get("authorization") == f"Bearer {_KEY}"
    body = json.loads(submit.read())
    assert body["model"] == "gpt-image-2"  # the provider slug, not the registry id
    assert body["prompt"] == "a teal fox"
    assert body.get("size") == "1024x1024"


def test_generate_real_records_a_priced_cost_event_and_reconciles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _image_ok)
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.image.generate("a teal fox", model=_MODEL))

    events = _cost_events(capsys.readouterr().out)
    assert events, "a cost event must be emitted"
    event = events[-1]
    assert event["meter"] == "openai" and event["unit"] == "usd"
    assert event["source"] == "priced"
    assert isinstance(event["amount"], int | float) and event["amount"] > 0
    # The reservation was reconciled to the same amount (a ledger 'actual' entry exists).
    ledger = tmp_path / "budget" / "ledger.jsonl"
    actual = [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line and json.loads(line).get("kind") == "actual"
    ]
    assert actual and actual[-1]["amount"] == pytest.approx(event["amount"])


# ---------------------------------------------------------------------------
# Real edit — multipart /v1/images/edits with the source (and any refs) as image[].
# ---------------------------------------------------------------------------


def test_edit_real_posts_multipart_with_the_source_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _image_ok)
    ctx = _ctx(tmp_path, dry_run=False)
    # The source image is a video-relative path the surface reads from the video dir.
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "artifacts" / "src.png").write_bytes(_PNG)

    out = _run(
        ctx,
        lambda: media.image.edit("artifacts/src.png", "make it night", model=_MODEL),
    )
    assert (tmp_path / out).is_file()

    submit = seen[0]
    assert submit.method == "POST"
    assert submit.url.path == "/v1/images/edits"
    assert submit.headers.get("authorization") == f"Bearer {_KEY}"
    content_type = submit.headers.get("content-type", "")
    assert content_type.startswith("multipart/form-data")
    raw = submit.read()
    assert b"image[]" in raw  # the source image is sent as an image[] part
    assert b"make it night" in raw


# ---------------------------------------------------------------------------
# Refusals — before any spend.
# ---------------------------------------------------------------------------


def test_generate_on_a_non_image_model_raises_capability_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A non-image model handed to the image surface must fail at the call, before any HTTP AND
    # before the secret is read (the capability check comes first). No video model is registered
    # yet, so inject one under the already-configured openai provider.
    from sfvf.providers import registry
    from sfvf.providers.registry import Model, PriceHint

    monkeypatch.setitem(
        registry.MODELS,
        "openai/fake-video",
        Model(
            id="openai/fake-video",
            provider="openai",
            slug="fake-video",
            kind="video",
            capabilities=frozenset({"video.generate"}),
            label="Fake Video",
            price=PriceHint("usd", "per_second", 0.1, "test"),
        ),
    )
    seen = _install_mock(monkeypatch, _image_ok)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(CapabilityError):
        _run(ctx, lambda: media.image.generate("x", model="openai/fake-video"))
    assert seen == []


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _image_ok)
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.image.generate("x", model=_MODEL))
    assert seen == []


def test_generate_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.image.generate("x", model=_MODEL)


def test_openai_provider_row_exists() -> None:
    # Sanity: the surface resolves the provider the model names.
    assert "openai" in PROVIDERS and PROVIDERS["openai"].meter == "openai"
