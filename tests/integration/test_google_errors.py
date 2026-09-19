"""Frozen contract — Stage P, P-5a hardening: the Google image adapter's error paths.

Three real, non-happy-path shapes that the P-5a review found the adapter mishandled — each must
surface as a clean `AdapterError`, never as an unhandled `AttributeError` / `JSONDecodeError` /
`binascii.Error`, and without echoing the offending input:

1. A safety-blocked Gemini candidate can carry `"content": null` (not an omitted key). Extracting
   the image must not do `None.get(...)`.
2. A malformed `GOOGLE_SA_JSON` secret must fail as a config `AdapterError` before any network call,
   and must not leak the raw secret text into the error (JSONDecodeError carries `.doc`).
3. A malformed base64 `inlineData.data` from the provider must fail as an `AdapterError`, not a bare
   `binascii.Error`.

HTTP is mocked exactly as the P-5a image contract does (one `_transport` serves the SA token
exchange and `:generateContent`); the SA is an ephemeral in-test RSA key.
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
from sfvf.providers.base import AdapterError

_MODEL = "google/gemini-3.1-flash-image"
_TOKEN = "ya29.mock-access-token-not-real"
_TOKEN_URI = "https://oauth2.googleapis.test/token"
_LEAK_MARKER = "leak-me-not-3f9c"


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


def _ctx(tmp: Path, *, secrets: dict[str, object] | None = None) -> Context:
    return Context(
        ContextFile(
            settings={},
            dry_run=False,
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


def _token_then(payload: dict):
    """SA token exchange -> {access_token}; generateContent -> the given payload."""

    def handler(request: httpx2.Request, seen: list[httpx2.Request]) -> httpx2.Response:
        if request.method == "POST" and request.url.path == "/token":
            return httpx2.Response(200, json={"access_token": _TOKEN, "expires_in": 3600})
        if request.method == "POST" and request.url.path.endswith(":generateContent"):
            return httpx2.Response(200, json=payload)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

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


def test_safety_blocked_content_null_raises_adaptererror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A blocked candidate with an explicit null content must not crash with AttributeError.
    _install_mock(monkeypatch, _token_then({"candidates": [{"content": None}]}))
    ctx = _ctx(tmp_path)
    with pytest.raises(AdapterError):
        _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))


def test_malformed_sa_json_raises_adaptererror_before_any_call_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _install_mock(monkeypatch, _token_then({"candidates": []}))
    ctx = _ctx(tmp_path, secrets={"GOOGLE_SA_JSON": '{"broken": "' + _LEAK_MARKER})
    with pytest.raises(AdapterError) as excinfo:
        _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))
    # Fails before any network call, and the raw secret text is not echoed into the error.
    assert seen == []
    assert _LEAK_MARKER not in str(excinfo.value)


def test_malformed_base64_image_data_raises_adaptererror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "a"}}]}}
        ]
    }
    _install_mock(monkeypatch, _token_then(payload))
    ctx = _ctx(tmp_path)
    with pytest.raises(AdapterError):
        _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))


def test_a_valid_response_still_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Guard: the hardening must not regress the happy path.
    png = b"\x89PNG\r\n\x1a\nOK"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "here"},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(png).decode(),
                            }
                        },
                    ]
                }
            }
        ]
    }
    _install_mock(monkeypatch, _token_then(payload))
    ctx = _ctx(tmp_path)
    out = _run(ctx, lambda: media.image.generate("a fox", model=_MODEL))
    assert (tmp_path / out).read_bytes() == png
