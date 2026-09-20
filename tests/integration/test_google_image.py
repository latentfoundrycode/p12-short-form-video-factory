"""Frozen contract — Stage P, P-5a: the Google (Vertex / Agent Platform) image adapter.

Google is the heaviest adapter: authentication is service-account OAuth, not a static key. The
adapter reads the service-account key JSON from the `GOOGLE_SA_JSON` secret, signs an RS256
SA-JWT (via the already-built `GoogleSaAuth`), exchanges it at the SA's `token_uri` for a Bearer
access token (cached), and calls the regional Vertex host. The GCP `project` is read from the
SA-JSON's own `project_id` (single source of truth); only the `region` is pinned in the Provider
row (default `us-central1`).

Image generation is SYNCHRONOUS via `:generateContent` with model `gemini-3.1-flash-image`
(Nano Banana 2): body carries `contents.parts` (a text part plus, for edits/refs, `inlineData`
parts with `mimeType`+base64 `data`) and `generationConfig.responseModalities == ["TEXT","IMAGE"]`
(both are required; image-only output is unsupported). The generated image comes back at
`candidates[0].content.parts[].inlineData.{data,mimeType}`. Cost is `priced` (fiat/usd), the
router prices it from `image_price`.

HTTP is exercised against httpx2.MockTransport by monkeypatching `sfvf.providers.google._transport`
(shared by both the SA token exchange and the API client). No live network. The service account is
an ephemeral in-test RSA key so `GoogleSaAuth` can really sign — nothing hardcoded.

The one shape read less verbatim from the docs (inline image bytes location) is pinned to the
best-documented reading and confirmed at the live smoke.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sfvf import media
from sfvf.context import BudgetConfig, Context, ContextFile, ContextPaths
from sfvf.providers import capabilities_offered, resolve

_MODEL = "google/gemini-3.1-flash-image"
_SLUG = "gemini-3.1-flash-image"
_TOKEN = "ya29.mock-access-token-not-real"
_TOKEN_URI = "https://oauth2.googleapis.test/token"
_PNG = b"\x89PNG\r\n\x1a\nGOOGLE-FAKE-IMAGE"


def _sa_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "sfvf-test-project",
            "private_key_id": "kid-1",
            "private_key": pem,
            "client_email": "sfvf@sfvf-test-project.iam.gserviceaccount.test",
            "client_id": "123",
            "token_uri": _TOKEN_URI,
        }
    )


_SA_JSON = _sa_json()


def _ctx(tmp: Path, *, dry_run: bool, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=dry_run,
            secrets={"GOOGLE_SA_JSON": _SA_JSON} if secrets is None else secrets,
            paths=ContextPaths(
                video=tmp, artifacts=tmp / "artifacts", steps=tmp / ".steps", shared=tmp
            ),
            budget=BudgetConfig(
                ledger_path=tmp / "budget" / "ledger.jsonl",
                per_day={"google": 1_000_000.0},
                estimates={},
            ),
        )
    )


def _image_response() -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "Here is your image."},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(_PNG).decode(),
                            }
                        },
                    ],
                }
            }
        ]
    }


def _handler():
    """SA token exchange -> {access_token}; generateContent -> an inlineData image part."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        host = request.url.host
        path = request.url.path
        if request.method == "POST" and path == "/token":
            return httpx2.Response(200, json={"access_token": _TOKEN, "expires_in": 3600})
        if request.method == "POST" and path.endswith(":generateContent"):
            # Live smoke (2026-09-20): gemini-3.1-flash-image is served on `global`, not
            # us-central1 (which 404s); the image model overrides the provider region.
            assert host == "aiplatform.googleapis.com"
            return httpx2.Response(200, json=_image_response())
        raise AssertionError(f"unexpected request: {request.method} {host}{path}")

    return handler


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx2.Request]:
    seen: list[httpx2.Request] = []

    def wrapped(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return handler(request, seen)

    def _transport() -> httpx2.MockTransport:
        return httpx2.MockTransport(wrapped)

    from sfvf.providers import google as google_adapter

    monkeypatch.setattr(google_adapter, "_transport", _transport)
    return seen


def _run(ctx: Context, fn):
    from sfvf._runtime import reset_active, set_active

    token = set_active(ctx)
    try:
        return fn()
    finally:
        reset_active(token)


def _gen_body(seen: list[httpx2.Request]) -> dict:
    call = next(r for r in seen if r.url.path.endswith(":generateContent"))
    return json.loads(call.read())


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
# Registry (google pinned fiat/usd, region us-central1; the Nano Banana 2 model)
# ---------------------------------------------------------------------------


def test_google_image_model_registered_fiat_usd() -> None:
    from sfvf.providers import PROVIDERS

    google = PROVIDERS["google"]
    assert google.meter_kind == "fiat" and google.unit == "usd"
    assert google.region == "us-central1"
    provider, model = resolve(_MODEL)
    assert provider.id == "google" and model.kind == "image" and model.slug == _SLUG
    assert {"image.generate", "image.edit", "image.refs"} <= model.capabilities
    assert "image.generate" in capabilities_offered({"GOOGLE_SA_JSON"})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_generate_dry_run_makes_no_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_r: httpx2.Request, _s: list[httpx2.Request]) -> httpx2.Response:
        raise AssertionError("dry_run must not hit the network")

    seen = _install_mock(monkeypatch, boom)
    ctx = _ctx(tmp_path, dry_run=True)
    out = _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))
    assert (tmp_path / out).is_file()
    assert seen == []


# ---------------------------------------------------------------------------
# Real generate — SA token exchange, regional host/path, decode inlineData
# ---------------------------------------------------------------------------


def test_generate_real_exchanges_token_calls_generatecontent_decodes_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _handler())
    ctx = _ctx(tmp_path, dry_run=False)
    out = _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))
    assert (tmp_path / out).read_bytes() == _PNG

    # SA token was exchanged at the SA's token_uri before the API call.
    assert any(r.method == "POST" and r.url.path == "/token" for r in seen)
    call = next(r for r in seen if r.url.path.endswith(":generateContent"))
    assert call.url.host == "aiplatform.googleapis.com"
    # project comes from the SA-JSON's project_id; the image model overrides region to `global`
    # (confirmed live: gemini-3.1-flash-image is global-only; us-central1 404s).
    assert call.url.path == (
        "/v1/projects/sfvf-test-project/locations/global"
        "/publishers/google/models/gemini-3.1-flash-image:generateContent"
    )
    assert call.headers.get("authorization") == f"Bearer {_TOKEN}"
    body = _gen_body(seen)
    assert body["generationConfig"]["responseModalities"] == ["TEXT", "IMAGE"]
    parts = body["contents"]["parts"]
    assert any(p.get("text") == "a fox" for p in parts)


def test_generate_records_a_priced_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _install_mock(monkeypatch, _handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))

    _, model = resolve(_MODEL)
    events = _cost_events(capsys.readouterr().out)
    assert events
    event = events[-1]
    assert event["meter"] == "google" and event["unit"] == "usd"
    assert event["source"] == "priced"
    assert event["amount"] == pytest.approx(model.price.amount)


# ---------------------------------------------------------------------------
# Edit — base image + refs cross as inlineData parts
# ---------------------------------------------------------------------------


def test_edit_sends_base_and_ref_images_as_inline_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _handler())
    ctx = _ctx(tmp_path, dry_run=False)
    (tmp_path / "base.png").write_bytes(_PNG)
    (tmp_path / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\nREF-IMAGE")

    out = _run(
        ctx,
        lambda: media.image.edit(
            "base.png",
            "make it night",
            model=_MODEL,
            refs=[{"kind": "character", "path": "ref.png"}],
        ),
    )
    assert (tmp_path / out).read_bytes() == _PNG
    parts = _gen_body(seen)["contents"]["parts"]
    inline = [p["inlineData"] for p in parts if "inlineData" in p]
    datas = {item["data"] for item in inline}
    assert base64.b64encode(_PNG).decode() in datas
    assert base64.b64encode(b"\x89PNG\r\n\x1a\nREF-IMAGE").decode() in datas
    assert all(item["mimeType"] == "image/png" for item in inline)
    assert any(p.get("text") == "make it night" for p in parts)


# ---------------------------------------------------------------------------
# Privacy — no credential in any URL
# ---------------------------------------------------------------------------


def test_no_credential_appears_in_any_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install_mock(monkeypatch, _handler())
    ctx = _ctx(tmp_path, dry_run=False)
    _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))

    sa = json.loads(_SA_JSON)
    for r in seen:
        url = str(r.url)
        assert _TOKEN not in url
        assert sa["private_key"] not in url
        assert sa["client_email"] not in url


# ---------------------------------------------------------------------------
# Error / refusal paths — before any spend where possible
# ---------------------------------------------------------------------------


def test_generate_missing_key_raises_before_any_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _handler())
    ctx = _ctx(tmp_path, dry_run=False, secrets={})
    with pytest.raises(KeyError):
        _run(ctx, lambda: media.image.generate("x", model=_MODEL))
    assert seen == []


def test_response_without_an_image_raises_adaptererror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sfvf.providers.base import AdapterError

    def text_only(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if request.url.path == "/token":
            return httpx2.Response(200, json={"access_token": _TOKEN, "expires_in": 3600})
        return httpx2.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "no image, sorry"}]}}]},
        )

    _install_mock(monkeypatch, text_only)
    ctx = _ctx(tmp_path, dry_run=False)
    with pytest.raises(AdapterError):
        _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))


def test_generate_requires_an_active_context() -> None:
    with pytest.raises(RuntimeError):
        media.image.generate("x", model=_MODEL)
