# TASK — web-sourcing inc6: SerpApi paid `web` tier (key-gated)

## Context
The `web` tier of `media.web.search(..., sources=("web",))` currently raises `NotImplementedError`.
Build it: a **SerpApi Google Images** search adapter behind the existing SSRF/byte/VLM pipeline. Owner
decisions (2026-09-22): provider = **SerpApi**; content-safety = **safeSearch strict** (`safe=active`),
no extra moderation; web-tier `licence="unknown"` (images may appear in produced videos). A frozen RED
contract is committed: `tests/integration/test_media_web_web.py` + updated surface/commons tests (do
not edit tests). This mirrors the increment-2 Openverse commons adapter — read
`sdk/sfvf/providers/openverse.py` and `tests/integration/test_media_web_commons.py` as the template.

## Scope (four files — the coherent provider increment, like inc2)
- **NEW** `sdk/sfvf/providers/serpapi.py` — the adapter.
- `sdk/sfvf/providers/registry.py` — add the SerpApi provider row.
- `app/core/meters.py` — add the SerpApi `METERS` entry (else `test_meters_registry` fails CI).
- `sdk/sfvf/media/web.py` — wire the `web` tier in `search()` (remove both `NotImplementedError` raises).
No other files. No new dependencies. No test edits.

## 1. `sdk/sfvf/providers/serpapi.py` (mirror openverse.py)
```python
"""SerpApi Google Images adapter — GET /search?engine=google_images for the paid `web` tier."""
from __future__ import annotations
from typing import Any
from urllib.parse import urlencode
from .._ratelimit import LIMITER
from ._http import parse_json, request

_BASE = "https://serpapi.com"
_TIMEOUT_S = 30.0
_MAX_PER_PAGE = 100  # SerpApi returns up to 100 images_results per search (ijn page)
LIMITER.configure("serpapi", max_concurrency=2, min_interval_s=0.0)

class _Anon:
    def headers(self) -> dict[str, str]:
        return {}   # SerpApi auth is the api_key QUERY param, not a header

def _client() -> Any:
    import httpx2
    return httpx2.Client(base_url=_BASE, timeout=_TIMEOUT_S)

def _synth_attribution(title: str, source: str) -> str:
    via = f" — via {source}" if source else ""
    return f'"{title}"{via} (web search; licence unknown)'

def search(query: str, *, limit: int = 10, licence: str | None = None,
           provider: Any = None, secrets: dict[str, str] | None = None) -> list[dict[str, Any]]:
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
        if r.get("unsafe") is True:          # safeSearch defence-in-depth: drop flagged items
            continue
        image_url = r.get("original")        # the full-resolution image URL
        if not image_url:                    # null/missing original -> nothing to source, skip
            continue
        title = r.get("title") or ""
        out.append({
            "source": "web",
            "url": image_url,
            "thumbnail": r.get("thumbnail") or "",
            "licence": "unknown",            # web-tier licence is always unknown (owner decision)
            "attribution": _synth_attribution(title or "Untitled", r.get("source") or ""),
            "width": int(r.get("original_width") or 0),
            "height": int(r.get("original_height") or 0),
            "title": title,
            "rank": i,
        })
        if len(out) >= limit:
            break
    return out
```
Notes: `request()` derives its error context from the PATH only (`url.split("?",1)[0]`), so the
`api_key` in the query never lands in an `AdapterError`/log — do not add the query to any error string.

## 2. `sdk/sfvf/providers/registry.py` — add the provider row (after the `openverse` row)
```python
    "serpapi": Provider(
        "serpapi",
        "SerpApi",
        ("SERPAPI_API_KEY",),
        "serpapi",
        "fiat",
        "usd",
        "https://serpapi.com",
        "serpapi",
        capabilities=frozenset({"web.images.web"}),
    ),
```
(`web.images.web` is already in `KNOWN_CAPABILITIES`. The `secret_names=("SERPAPI_API_KEY",)` makes
`capabilities_offered` gate the capability on the key automatically — no other change needed.)

## 3. `app/core/meters.py` — add the meters row (next to the other fiat providers)
```python
    "serpapi": MeterInfo(kind="fiat", provider="SerpApi", unit="usd"),
```

## 4. `sdk/sfvf/media/web.py` — wire the web tier in `search()`
- Delete the early `if "web" in sources: raise NotImplementedError(...)` guard.
- In the per-tier loop, replace the `else:  # "web"` `raise NotImplementedError(...)` with a dispatch
  that mirrors the `commons` branch:
```python
        else:  # "web"
            provider = PROVIDERS["serpapi"]
            secrets = {name: ctx.secret(name) for name in provider.secret_names}
            adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
            out.extend(
                adapter.search(query, limit=limit, licence=licence, provider=provider, secrets=secrets)
            )
```
`ctx.secret("SERPAPI_API_KEY")` raises `KeyError` when the key is not configured (fail-closed) — leave
that behaviour. Do not change the `sources` validation, the dry-run branch, or the URL-dedup tail.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_commons.py tests/sdk/test_providers_registry.py tests/core/test_meters.py -q`
  → **all pass**.
- `python -m ruff format --check` and `python -m ruff check` on the four changed files → clean.
- `PYTHONPATH=sdk python -m mypy sdk/sfvf/providers/serpapi.py sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows exactly the four files above.
