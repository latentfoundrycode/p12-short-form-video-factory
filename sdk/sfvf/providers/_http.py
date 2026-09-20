"""HTTP behavior shared by provider adapters."""

from __future__ import annotations

import math
from typing import Any


def _retry_after_s(value: str | None) -> float:
    if value is None:
        return 0.0
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(seconds) or seconds < 0:
        return 0.0
    return seconds


def _truncate(text: str) -> str:
    return text[:200]


def _redact(text: str, auth_headers: dict[str, str]) -> str:
    """Remove the credentials we sent (each auth header value, and the token after a scheme
    prefix like 'Bearer'/'Basic') from an error body, so a reflected credential can't land in
    the detail. Precise — only the exact strings we transmitted are removed."""
    secrets: set[str] = set()
    for value in auth_headers.values():
        if value:
            secrets.add(value)
            if " " in value:
                secrets.add(value.split(" ", 1)[1])  # token after a scheme (Bearer/Basic)
    for secret in secrets:
        text = text.replace(secret, "[redacted]")
    return text


def request(
    client: Any,
    method: str,
    url: str,
    *,
    provider: str,
    auth: Any,
    limiter: Any,
    json: Any = None,
    files: Any = None,
    data: Any = None,
    headers: dict[str, str] | None = None,
    max_attempts: int = 4,
) -> Any:
    merged = dict(headers or {})
    auth_headers = auth.headers()
    merged.update(auth_headers)
    path = url.split("?", 1)[0]
    where = f"{method} {path}"

    for attempt in range(max_attempts):
        with limiter.slot(provider):
            response = client.request(
                method,
                url,
                headers=merged,
                json=json,
                files=files,
                data=data,
            )
        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 429 and attempt < max_attempts - 1:
            limiter.penalize(provider, _retry_after_s(response.headers.get("Retry-After")))
            continue

        from .base import AdapterError

        if response.status_code == 401:
            detail = "authentication failed"
        elif response.status_code == 403:
            detail = "authorization failed"
        else:
            detail = _truncate(_redact(response.text, auth_headers))
        raise AdapterError(
            provider,
            status=response.status_code,
            where=where,
            detail=detail,
        )

    from .base import AdapterError

    raise AdapterError(
        provider,
        status=429,
        where=where,
        detail="rate limited after retries",
    )


def parse_json(response: Any, *, provider: str, where: str) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception as exc:
        from .base import AdapterError

        raise AdapterError(
            provider,
            status=response.status_code,
            where=where,
            detail="invalid JSON body",
        ) from exc
    if not isinstance(data, dict):
        from .base import AdapterError

        raise AdapterError(
            provider,
            status=response.status_code,
            where=where,
            detail="non-object JSON body",
        )
    return data


def download_bytes(client: Any, url: str, *, provider: str, media: str) -> bytes:
    """GET a signed/public asset URL (no auth header) and return its bytes,
    or raise AdapterError.
    """
    response = client.get(url)
    if not 200 <= response.status_code < 300:
        from .base import AdapterError

        raise AdapterError(
            provider,
            status=response.status_code,
            where="download",
            detail=f"{media} download failed",
        )
    content: bytes = response.content
    return content
