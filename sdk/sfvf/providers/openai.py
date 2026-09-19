"""OpenAI image adapter — synchronous /v1/images/generations and /v1/images/edits."""

from __future__ import annotations

import base64
from typing import Any

from .._ratelimit import LIMITER
from ._auth import BearerAuth
from ._http import parse_json, request
from .base import AdapterError, Output

_MEDIA_TYPE = "image/png"


def _client(base_url: str) -> Any:
    import httpx2

    return httpx2.Client(base_url=base_url, timeout=180.0)


def image_price(model: Any, size: str | None) -> float:
    return float(model.price.amount)


def _decode(resp: Any) -> Output:
    data = parse_json(resp, provider="openai", where="POST /v1/images")
    try:
        b64 = data["data"][0]["b64_json"]
        raw = base64.b64decode(b64)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AdapterError(
            "openai",
            status=resp.status_code,
            where="POST /v1/images",
            detail="missing b64_json image data",
        ) from exc
    return Output(data=raw, media_type=_MEDIA_TYPE)


def generate(
    prompt: str,
    *,
    model: Any,
    provider: Any,
    size: str | None,
    secrets: dict[str, str],
) -> Output:
    auth = BearerAuth(secrets["OPENAI_API_KEY"])
    body: dict[str, Any] = {"model": model.slug, "prompt": prompt, "n": 1}
    if size:
        body["size"] = size
    with _client(provider.base_url) as client:
        resp = request(
            client,
            "POST",
            "/v1/images/generations",
            provider="openai",
            auth=auth,
            limiter=LIMITER,
            json=body,
        )
    return _decode(resp)


def edit(
    image_bytes: bytes,
    prompt: str,
    *,
    model: Any,
    provider: Any,
    size: str | None,
    refs_bytes: list[bytes],
    secrets: dict[str, str],
) -> Output:
    auth = BearerAuth(secrets["OPENAI_API_KEY"])
    files = [("image[]", ("image.png", image_bytes, "image/png"))]
    for i, rb in enumerate(refs_bytes or []):
        files.append(("image[]", (f"ref{i}.png", rb, "image/png")))
    data: dict[str, Any] = {"model": model.slug, "prompt": prompt, "n": "1"}
    if size:
        data["size"] = size
    with _client(provider.base_url) as client:
        resp = request(
            client,
            "POST",
            "/v1/images/edits",
            provider="openai",
            auth=auth,
            limiter=LIMITER,
            files=files,
            data=data,
        )
    return _decode(resp)
