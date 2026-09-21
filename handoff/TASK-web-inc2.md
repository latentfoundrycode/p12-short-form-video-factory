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
