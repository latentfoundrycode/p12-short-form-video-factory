"""Openverse image-search adapter — anonymous GET /images/ for the commons tier."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .._ratelimit import LIMITER
from ._http import parse_json, request

_BASE = "https://api.openverse.org/v1"
_TIMEOUT_S = 30.0
_ANON_MAX_PAGE_SIZE = 20  # anonymous Openverse rejects page_size > 20 (HTTP 401)

# Anonymous Openverse throttle: ~20 requests/min. One at a time, >= 3s apart.
LIMITER.configure("openverse", max_concurrency=1, min_interval_s=3.0)


class _Anon:
    """Anonymous auth: Openverse image search needs no credentials."""

    def headers(self) -> dict[str, str]:
        return {}


def _client() -> Any:
    import httpx2

    return httpx2.Client(base_url=_BASE, timeout=_TIMEOUT_S)


def search(
    query: str,
    *,
    limit: int = 20,
    licence: str | None = None,
    provider: Any = None,
    secrets: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:  # nothing requested -> no call (Openverse 400s on <= 0)
        return []
    page_size = min(limit, _ANON_MAX_PAGE_SIZE)
    params: dict[str, Any] = {"q": query, "page_size": page_size}
    if licence:
        params["license"] = licence
    url = f"/images/?{urlencode(params)}"
    with _client() as client:
        resp = request(client, "GET", url, provider="openverse", auth=_Anon(), limiter=LIMITER)
    data = parse_json(resp, provider="openverse", where="GET /images/")
    out: list[dict[str, Any]] = []
    for i, r in enumerate(data.get("results") or []):
        if not isinstance(r, dict):
            continue
        image_url = r.get("url")
        if not image_url:  # schema permits null url -> nothing to source, skip
            continue
        lic = r.get("license") or ""
        ver = r.get("license_version") or ""
        licence_str = f"{lic} {ver}".strip() or "unknown"
        out.append(
            {
                "source": "commons",
                "url": image_url,
                "thumbnail": r.get("thumbnail") or "",
                "licence": licence_str,
                "attribution": r.get("attribution") or "",
                "width": int(r.get("width") or 0),
                "height": int(r.get("height") or 0),
                "title": r.get("title") or "",
                "rank": i,
            }
        )
    return out
