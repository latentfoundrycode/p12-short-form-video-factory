"""Openverse image-search adapter — anonymous GET /images/ for the commons tier."""

from __future__ import annotations

from typing import Any

from .base import AdapterError

_BASE = "https://api.openverse.org/v1"
_TIMEOUT_S = 30.0


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
    params: dict[str, Any] = {"q": query, "page_size": limit}
    if licence:
        params["license"] = licence
    with _client() as client:
        resp = client.get("/images/", params=params)  # anonymous: no auth header
    if resp.status_code != 200:
        raise AdapterError("openverse", status=resp.status_code, where="GET /images/")
    results = resp.json().get("results", [])
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        licence_str = f"{r.get('license', '')} {r.get('license_version', '')}".strip()
        out.append(
            {
                "source": "commons",
                "url": r["url"],  # the direct image file
                "thumbnail": r.get("thumbnail", ""),
                "licence": licence_str or "unknown",
                "attribution": r.get("attribution", ""),
                "width": int(r.get("width") or 0),
                "height": int(r.get("height") or 0),
                "title": r.get("title", ""),
                "rank": i,
            }
        )
    return out
