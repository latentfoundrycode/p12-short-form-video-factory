"""SerpApi Google Images adapter — GET /search?engine=google_images for the paid `web` tier."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .._ratelimit import LIMITER
from .._runtime import current_context
from ._http import parse_json, request
from .base import AdapterError

_BASE = "https://serpapi.com"
_TIMEOUT_S = 30.0
# SerpApi's priciest standard plan (Starter, $25/1k). Conservative default when
# the owner has not configured estimates["serpapi"]; they should set their
# actual plan rate there for precise accounting.
_SEARCH_PRICE_DEFAULT_USD = 0.025
LIMITER.configure("serpapi", max_concurrency=2, min_interval_s=0.0)


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
    ctx = current_context()
    price = ctx.budget_estimate(provider.meter) or _SEARCH_PRICE_DEFAULT_USD
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=price)
    billed = False
    try:
        with _client() as client:
            # request about to be dispatched; an ambiguous failure from here
            # RETAINS (fail closed)
            billed = True
            try:
                resp = request(
                    client,
                    "GET",
                    url,
                    provider="serpapi",
                    auth=_Anon(),
                    limiter=LIMITER,
                    redact=[key],
                )
            except AdapterError:
                # request() raises only for a non-2xx response (after its 429 retries); SerpApi does
                # not bill a failed search, so this is CONFIRMED unbilled -> release in finally.
                billed = False
                raise
        # request() returned -> a 2xx -> SerpApi billed this search. From here (parse + mapping) any
        # failure RETAINS the estimate: the search was billed even if the body is unusable.
        data = parse_json(resp, provider="serpapi", where="GET /search")
        # SerpApi serves repeated queries from its cache and marks them free
        # ("Cached"); only a fresh ("Success"/unknown) 200 is billed. Fail
        # toward charging on an unknown status.
        meta = data.get("search_metadata")
        cached = isinstance(meta, dict) and str(meta.get("status") or "").lower() == "cached"
        if cached:
            # a cached SerpApi response is free regardless of whether its body maps cleanly;
            # reconcile to $0 NOW so a later mapping failure cannot leave the reservation charged.
            ctx.record_cost(
                provider.meter, provider.unit, price, "cached", token=token, cached=True
            )
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
        if not cached:
            ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
        return out
    finally:
        if not billed:
            ctx._budget_reconcile(token, actual=0.0, note="released")
