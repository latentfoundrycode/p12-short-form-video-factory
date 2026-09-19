# TASK — P-3: media.image surface + OpenAI image adapter

## Goal (one sentence)
Add the provider-agnostic `media.image` surface (`generate`/`edit`, SDK §6.2) and the first adapter behind
it — OpenAI, synchronous, Bearer — plus `base.Output`, the `openai/gpt-image-2` registry row, and a small
multipart extension to the kit's `request()`, so the frozen contract goes green.

## Spec (docs/PROVIDER_LAYER_PLAN.md §3.4, P-3) — authoritative
The surface resolves a model id, checks it can do the image op (before any spend AND before reading the
secret), reserves the per-call price, calls the adapter, writes the decoded image as an artifact, and records
the cost via `ctx.record_cost(...)` tagged `priced`. `dry_run` returns a free placeholder image (no key, no
HTTP). OpenAI images are SYNCHRONOUS (no polling): `/v1/images/generations` (JSON) and `/v1/images/edits`
(multipart, `image[]` files), returning base64 image data.

## Frozen contract (already committed — do NOT edit)
`tests/integration/test_image_openai.py`. Make it pass; the full suite must stay green.

## Import-weight rule
`import sfvf.media.image` and `import sfvf.providers.openai` must need stdlib only at module top; lazy-import
`httpx2` inside the function that makes the call (mirror `agents.py`).

## What to create / change

### 1. `sdk/sfvf/providers/base.py` — add `Output`
```python
@dataclass(frozen=True)
class Output:
    data: bytes
    media_type: str
```

### 2. `sdk/sfvf/providers/registry.py` — register the model
Add to `MODELS` (the seeding rule now permits it — the adapter exists):
```python
"openai/gpt-image-2": Model(
    id="openai/gpt-image-2", provider="openai", slug="gpt-image-2", kind="image",
    capabilities=frozenset({"image.generate", "image.edit"}), label="OpenAI GPT Image 2",
    price=PriceHint(unit="usd", basis="per_image", amount=0.04, verified="2026-09-19"),
    notes="priced per image; a single figure for now — size/quality-dependent pricing is a later "
          "refinement, and the real per-image cost is confirmed at the attended live smoke",
),
```

### 3. `sdk/sfvf/providers/_http.py` — additive multipart support (keeps all P-2 behaviour)
`request(...)` gains two optional keyword params `files: Any = None, data: Any = None`, forwarded to the
client call: `client.request(method, url, headers=merged, json=json, files=files, data=data)`. Everything
else (auth merge, 429 retry, hygienic error, path-strips-query) is unchanged, so the P-2 contract stays green.

### 4. `sdk/sfvf/providers/openai.py` — the adapter (new; replaces nothing)
```python
"""OpenAI image adapter — synchronous /v1/images/generations and /v1/images/edits."""
from __future__ import annotations
import base64
from typing import Any
from .._ratelimit import LIMITER
from ._auth import BearerAuth
from ._http import parse_json, request
from .base import AdapterError, Output

_MEDIA_TYPE = "image/png"

def _client(base_url: str) -> Any:            # monkeypatched in tests; lazy httpx2 in prod
    import httpx2
    return httpx2.Client(base_url=base_url, timeout=180.0)

def image_price(model: Any, size: str | None) -> float:
    return float(model.price.amount)          # per image; size-dependent pricing is a later refinement

def _decode(resp: Any) -> Output:
    data = parse_json(resp, provider="openai", where="POST /v1/images")
    try:
        b64 = data["data"][0]["b64_json"]
        raw = base64.b64decode(b64)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AdapterError("openai", status=resp.status_code, where="POST /v1/images",
                           detail="missing b64_json image data") from exc
    return Output(data=raw, media_type=_MEDIA_TYPE)

def generate(prompt: str, *, model: Any, provider: Any, size: str | None, secrets: dict[str, str]) -> Output:
    auth = BearerAuth(secrets["OPENAI_API_KEY"])
    body: dict[str, Any] = {"model": model.slug, "prompt": prompt, "n": 1}
    if size:
        body["size"] = size
    with _client(provider.base_url) as client:
        resp = request(client, "POST", "/v1/images/generations", provider="openai",
                       auth=auth, limiter=LIMITER, json=body)
    return _decode(resp)

def edit(image_bytes: bytes, prompt: str, *, model: Any, provider: Any, size: str | None,
         refs_bytes: list[bytes], secrets: dict[str, str]) -> Output:
    auth = BearerAuth(secrets["OPENAI_API_KEY"])
    files = [("image[]", ("image.png", image_bytes, "image/png"))]
    for i, rb in enumerate(refs_bytes or []):
        files.append(("image[]", (f"ref{i}.png", rb, "image/png")))
    data: dict[str, Any] = {"model": model.slug, "prompt": prompt, "n": "1"}
    if size:
        data["size"] = size
    with _client(provider.base_url) as client:
        resp = request(client, "POST", "/v1/images/edits", provider="openai",
                       auth=auth, limiter=LIMITER, files=files, data=data)
    return _decode(resp)
```
(The `Authorization: Bearer <key>` header is applied by `request()` from `auth`; do not also put the key in
a query string. `request()` sets the JSON content-type for `generate`; for `edit`, passing `files`/`data`
lets httpx set the multipart content-type + boundary.)

### 5. `sdk/sfvf/media/image.py` — the surface (new)
Module-top imports: `importlib`, and from the SDK `current_context` (`.._runtime`), `solid_image`
(`.._ffmpeg`), `_artifact`/`_sha8` (`.graphics`), `resolve`/`CapabilityError` (`..providers`). Then:
```python
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_DEFAULT_W = _DEFAULT_H = 1024

def generate(prompt, *, model, refs=None, size=None) -> str:
    ctx = current_context()                                    # RuntimeError if no active context
    stem = _sha8(["image.generate", prompt, model, refs, size])
    if ctx.dry_run:
        dest, rel = _artifact(ctx, f"image-{stem}.png")
        solid_image(dest, width=_DEFAULT_W, height=_DEFAULT_H)
        return rel
    provider, mdl = resolve(model)
    if mdl.kind != "image" or "image.generate" not in mdl.capabilities:   # BEFORE the secret read
        raise CapabilityError(f"model {model!r} cannot generate images")
    secrets = {n: ctx.secret(n) for n in provider.secret_names}           # KeyError if a key is missing
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    price = adapter.image_price(mdl, size)
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=price)
    out = adapter.generate(prompt, model=mdl, provider=provider, size=size, secrets=secrets)
    dest, rel = _artifact(ctx, f"image-{stem}.{_EXT.get(out.media_type, 'png')}")
    dest.write_bytes(out.data)
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    return rel

def edit(image, prompt, *, model, refs=None) -> str:
    ctx = current_context()
    stem = _sha8(["image.edit", image, prompt, model, refs])
    if ctx.dry_run:
        dest, rel = _artifact(ctx, f"image-{stem}.png")
        solid_image(dest, width=_DEFAULT_W, height=_DEFAULT_H)
        return rel
    provider, mdl = resolve(model)
    if mdl.kind != "image" or "image.edit" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} cannot edit images")
    secrets = {n: ctx.secret(n) for n in provider.secret_names}
    image_bytes = (ctx.paths.video / image).read_bytes()
    refs_bytes = [(ctx.paths.video / r["path"]).read_bytes() for r in (refs or [])]
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    price = adapter.image_price(mdl, None)
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=price)
    out = adapter.edit(image_bytes, prompt, model=mdl, provider=provider, size=None,
                       refs_bytes=refs_bytes, secrets=secrets)
    dest, rel = _artifact(ctx, f"image-{stem}.{_EXT.get(out.media_type, 'png')}")
    dest.write_bytes(out.data)
    ctx.record_cost(provider.meter, provider.unit, price, "priced", token=token)
    return rel
```
Order matters: `current_context()` first (so a missing context raises before anything), then dry-run, then
resolve + capability check (raises `CapabilityError` before any spend AND before the secret read), then
secrets (`KeyError` before any HTTP).

### 6. `sdk/sfvf/media/__init__.py` — export `image`
Add `image` to the `from . import (...)` line and to `__all__`, alongside `edit, graphics, speech, video`.

## Constraints / do-nots
- Create/edit ONLY: `sdk/sfvf/media/image.py` (new), `sdk/sfvf/providers/openai.py` (new),
  `sdk/sfvf/providers/base.py`, `sdk/sfvf/providers/registry.py`, `sdk/sfvf/providers/_http.py`,
  `sdk/sfvf/media/__init__.py`. Do NOT edit any test or other file.
- No `app.*` import; no new dependency (httpx2 is pre-existing, lazy-imported). No key in a URL/query.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/media/image.py`
- `sdk/sfvf/media/__init__.py`
- `sdk/sfvf/providers/openai.py`
- `sdk/sfvf/providers/base.py`
- `sdk/sfvf/providers/registry.py`
- `sdk/sfvf/providers/_http.py`

## Verify (from the worktree; set `PYTHONPATH` to the worktree `sdk`)
- `-m pytest tests/integration/test_image_openai.py -q` → all pass.
- `-m pytest tests/sdk/test_providers_registry.py tests/sdk/test_providers_kit.py -q` → still green
  (registry row + the additive `_http` change must not break P-1/P-2 contracts).
- `-m pytest -q` (full) → green apart from the pre-existing HyperFrames/chrome env failures.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
