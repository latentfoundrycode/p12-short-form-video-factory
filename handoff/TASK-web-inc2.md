# TASK — web-image-sourcing increment 2: Openverse `commons` tier (real search)

Frozen RED contracts:
- `tests/sdk/test_providers_registry.py` (openverse provider row; keyless; provider-level cap)
- `tests/registry/test_web_images_vocab.py` (web.images.commons offered keylessly; web tier not)
- `tests/integration/test_media_web_commons.py` (mocked-HTTP: request shape + ImageCandidate mapping)

Design: `docs/DESIGN-web-image-sourcing.md` §3–§6. This increment makes the `commons` tier REAL:
register a KEYLESS Openverse provider, build its adapter, and wire `media.web.search`'s real (non-
dry-run) path for `sources=("commons",)`. No network in tests (mocked). The `web` tier stays
`NotImplementedError`. NO budget metering for commons (it is free).

## Scope (these files)
- `sdk/sfvf/providers/registry.py` (add the `openverse` provider row)
- `sdk/sfvf/providers/openverse.py` (NEW adapter)
- `sdk/sfvf/media/web.py` (wire `search`'s real path for the commons tier)
Do NOT touch tests, docs/, handoff/, requirements, CI, other providers/adapters.

## 1. `registry.py` — the keyless Openverse provider
Add to `PROVIDERS` (mind the positional field order: id, label, secret_names, meter, meter_kind, unit,
base_url, adapter, capabilities):
```python
    "openverse": Provider(
        "openverse", "Openverse", (),
        "openverse", "fiat", "usd",
        "https://api.openverse.org/v1", "openverse",
        capabilities=frozenset({"web.images.commons"}),
    ),
```
`secret_names=()` — anonymous/keyless. (The registry helpers already treat an empty tuple as
"always configured", so this capability is offered whenever the provider row is present.)

## 2. `sdk/sfvf/providers/openverse.py` (NEW)
An adapter with a patchable client seam and a `search` that returns plain dicts shaped like
`media.web.ImageCandidate` (return dicts — do NOT import ImageCandidate, avoid a circular import):
```python
from __future__ import annotations

from typing import Any

import httpx2

from .base import AdapterError

_BASE = "https://api.openverse.org/v1"
_TIMEOUT_S = 30.0


def _client() -> httpx2.Client:
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
        resp = client.get("/images/", params=params)   # anonymous: no auth header
    if resp.status_code != 200:
        # clean provider error (RuntimeError subclass); do not leak internals
        raise AdapterError(f"Openverse image search failed: HTTP {resp.status_code}")
    results = resp.json().get("results", [])
    out: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        licence_str = f"{r.get('license', '')} {r.get('license_version', '')}".strip()
        out.append(
            {
                "source": "commons",
                "url": r["url"],                       # the direct image file
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
```
(If `AdapterError`'s constructor differs, match the existing usage in the other adapters. `provider`
and `secrets` are accepted for interface symmetry and currently unused — keyless.)

## 3. `sdk/sfvf/media/web.py` — wire `search`'s real path
Replace `search`'s `raise NotImplementedError(...)` (the non-dry-run path) with per-tier dispatch. Keep
the existing `sources` validation and the dry-run stub branch unchanged.
```python
    # (after the dry-run branch)
    import importlib

    from ..providers.registry import PROVIDERS

    out: list[ImageCandidate] = []
    for tier in sources:
        if tier == "commons":
            provider = PROVIDERS["openverse"]
            secrets = {name: ctx.secret(name) for name in provider.secret_names}  # {} — keyless
            adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
            out.extend(
                adapter.search(query, limit=limit, licence=licence, provider=provider, secrets=secrets)
            )
        else:  # "web"
            raise NotImplementedError("media.web.search web tier is built in increment 6")
    # URL-deduplicate across tiers, preserving first-seen order (design §3.1).
    seen: set[str] = set()
    deduped: list[ImageCandidate] = []
    for c in out:
        if c["url"] not in seen:
            seen.add(c["url"])
            deduped.append(c)
    return deduped
```
`fetch`/`check_relevance`/`source` real paths stay `NotImplementedError` (later increments).

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/sdk/test_providers_registry.py tests/registry/ -q` — all pass.
- `ruff check` + `ruff format --check` + `mypy` clean on the three changed/new files.
- `git diff` (+ new file) shows exactly `registry.py`, `openverse.py`, `media/web.py`.

## Round 2 (cross-family Review B — live-verified fixes)
Review B ran the REAL Openverse API and found the mock encoded wrong assumptions, plus a CI failure.
Five fixes, across `app/core/meters.py`, `sdk/sfvf/providers/openverse.py`, `sdk/sfvf/media/web.py`.

### R2.1 — METERS entry (fixes CI: `tests/core/test_meters_registry.py`)
In `app/core/meters.py`'s `METERS` dict add (kind/unit must match the registry row):
```python
    "openverse": MeterInfo(kind="fiat", provider="Openverse", unit="usd"),
```

### R2.2 — Rewrite the adapter through the shared kit + caps + null handling (`providers/openverse.py`)
Use the central rate limiter + retry + hygienic parser (like `openai.py`), cap page_size to the
anonymous max, short-circuit non-positive limits, and tolerate schema-valid nulls:
```python
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from .._ratelimit import LIMITER
from ._http import parse_json, request

_BASE = "https://api.openverse.org/v1"
_TIMEOUT_S = 30.0
_ANON_MAX_PAGE_SIZE = 20   # anonymous Openverse rejects page_size > 20 (HTTP 401)

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
    if limit <= 0:                     # nothing requested -> no call (Openverse 400s on <= 0)
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
        if not image_url:              # schema permits null url -> nothing to source, skip
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
```
Note `r.get(k) or ""` (not `r.get(k, "")`) — a key PRESENT with a null value must coerce to the
default. `rank = i` is the enumerate index (over the RAW results), so a skipped null-url result leaves
a gap in ranks, which is fine (rank = provider rank).

### R2.3 — Reject the unsupported tier before dispatch (`media/web.py`)
In `search`'s real path, BEFORE the per-tier dispatch loop that calls the adapter, reject unimplemented
tiers so a mixed `("commons","web")` request makes no Openverse call then fails:
```python
    if "web" in sources:
        raise NotImplementedError("media.web.search web tier is built in increment 6")
```
(Keep the `sources` validation and the commons dispatch + URL-dedup otherwise unchanged.)

## Acceptance (round 2)
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/sdk/test_providers_registry.py tests/registry/ tests/core/test_meters_registry.py tests/core/test_meters.py -q` — all pass.
- `ruff check` + `ruff format --check` + `mypy` clean on `app/core/meters.py`, `sdk/sfvf/providers/openverse.py`, `sdk/sfvf/media/web.py`.
- `git diff` shows exactly those three files.

## Round 3 (commons attribution guarantee + malformed-results guard)
Cross-family Review B r2. In `sdk/sfvf/providers/openverse.py::search` (ONLY this file):
1. Guard a non-list `results` (malformed 200): after parse_json, do
   `results = data.get("results"); if not isinstance(results, list): results = []` and iterate
   `results` (not `data.get("results") or []`).
2. Enforce the SDK §6.8a commons guarantee (every result carries a licence AND attribution):
   - `lic = r.get("license") or ""`; `if not lic: continue`  # drop a licence-less row (not a valid
     commons/licensed result). licence_str is then `f"{lic} {ver}".strip()` (never "unknown"; drop the
     old `or "unknown"`).
   - attribution: `attribution = r.get("attribution") or _synth_attribution(r, licence_str)` where a
     module helper synthesises a NON-EMPTY string from the available fields, e.g.:
     ```python
     def _synth_attribution(r: dict[str, Any], licence_str: str) -> str:
         title = r.get("title") or "Untitled"
         creator = r.get("creator")
         who = f" by {creator}" if creator else ""
         return f'"{title}"{who} — {licence_str} (via Openverse)'
     ```
   Use `attribution` for the candidate's `attribution` field.
Everything else (page_size cap, limit<=0, null url/thumbnail/title coercion, the shared-kit routing,
rank=i) unchanged. Frozen tests:
`test_commons_results_always_carry_a_licence_and_non_empty_attribution`,
`test_commons_search_tolerates_a_non_list_results_field`, and the existing commons tests still pass.
