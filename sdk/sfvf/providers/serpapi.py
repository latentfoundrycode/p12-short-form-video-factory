"""SerpApi Google Images adapter — GET /search?engine=google_images for the paid `web` tier."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .._ratelimit import LIMITER
from ._http import parse_json, request

_BASE = "https://serpapi.com"
_TIMEOUT_S = 30.0
_SEARCH_PRICE_USD = 0.02  # conservative per-search estimate; >= SerpApi's standard plan rates
LIMITER.configure("serpapi", max_concurrency=2, min_interval_s=0.0)


def search_price() -> float:
    """Per-search cost used to reserve budget (SerpApi bills per successful search)."""
    return _SEARCH_PRICE_USD


class _Anon:
    def headers(self) -> dict[str, str]:
        return {}  # SerpApi auth is the api_key QUERY param, not a header


def _client() -> Any:
    import httpx2

    return httpx2.Client(base_url=_BASE, timeout=_TIMEOUT_S)


def _synth_attribution(title: str, source: str) -> str:
    via = f" — via {source}" if source else ""
    return f'"{title}"{via} (web search; licence unknown)'


def search(
    query: str,
    *,
    limit: int = 10,
    licence: str | None = None,
    provider: Any = None,
    secrets: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    key = (secrets or {}).get("SERPAPI_API_KEY", "")
    if not key:
        raise RuntimeError("serpapi: SERPAPI_API_KEY is required for the web tier")
    params = {"engine": "google_images", "q": query, "safe": "active", "ijn": 0, "api_key": key}
    url = f"/search?{urlencode(params)}"
    with _client() as client:
        resp = request(client, "GET", url, provider="serpapi", auth=_Anon(), limiter=LIMITER)
    data = parse_json(resp, provider="serpapi", where="GET /search")
    results = data.get("images_results")
    if not isinstance(results, list):
        results = []
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            continue
        if r.get("unsafe") is True:  # safeSearch defence-in-depth: drop flagged items
            continue
        image_url = r.get("original")  # the full-resolution image URL
        if not image_url:  # null/missing original -> nothing to source, skip
            continue
        title = r.get("title") or ""
        out.append(
            {
                "source": "web",
                "url": image_url,
                "thumbnail": r.get("thumbnail") or "",
                "licence": "unknown",  # web-tier licence is always unknown (owner decision)
                "attribution": _synth_attribution(title or "Untitled", r.get("source") or ""),
                "width": int(r.get("original_width") or 0),
                "height": int(r.get("original_height") or 0),
                "title": title,
                "rank": i,
            }
        )
        if len(out) >= limit:
            break
    return out
