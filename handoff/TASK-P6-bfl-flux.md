# TASK — P-6: Black Forest Labs (Flux) image adapter

## Goal (one sentence)
Add the BFL Flux image adapter behind the existing `media.image` surface (async submit→poll→download,
`x-key` auth) plus the two `bfl/*` registry rows, so the frozen contract goes green — no surface change.

## Spec (BFL API pinned in docs/PROJECT_STATUS.md) — authoritative
BFL is ASYNCHRONOUS with a custom-header credential: `POST /v1/<slug>` with header `x-key: <BFL_API_KEY>`
returns `{id, polling_url, cost, ...}`; poll `GET /v1/get_result?id=<id>` until `status == "Ready"`; the
image is a signed URL at `result.sample`, downloaded (no auth on that GET). The adapter does all of this
inside `generate`/`edit` and returns an `Output`, exactly like the OpenAI adapter — the media.image surface
is unchanged. Cost is priced per image (a pinned credits figure; source "priced") for this first cut.

## Frozen contract (already committed — do NOT edit)
`tests/integration/test_image_bfl.py`. Make it pass; the full suite must stay green.

## Import-weight rule
`import sfvf.providers.bfl` needs stdlib only at module top; lazy-import `httpx2` inside `_client`.

## What to create / change

### 1. `sdk/sfvf/providers/registry.py` — two model rows
Add to `MODELS`:
```python
"bfl/flux-1.1-pro": Model(
    id="bfl/flux-1.1-pro", provider="bfl", slug="flux-pro-1.1", kind="image",
    capabilities=frozenset({"image.generate"}), label="BFL FLUX1.1 [pro]",
    price=PriceHint(unit="credits", basis="per_image", amount=4.0, verified="2026-09-19"),
    notes="priced ~4 credits/image (1 credit = $0.01); confirm at the attended live smoke",
),
"bfl/flux-kontext-pro": Model(
    id="bfl/flux-kontext-pro", provider="bfl", slug="flux-kontext-pro", kind="image",
    capabilities=frozenset({"image.edit"}), label="BFL FLUX.1 Kontext [pro]",
    price=PriceHint(unit="credits", basis="per_image", amount=4.0, verified="2026-09-19"),
    notes="reference editing via input_image; priced ~4 credits/image; confirm at the live smoke",
),
```
(Generate is offered only by `flux-1.1-pro`, edit only by `flux-kontext-pro`, so the surface's capability
checks route each to the right endpoint and body shape without ambiguity.)

### 2. `sdk/sfvf/providers/bfl.py` (new) — the adapter (same interface as `openai.py`)
```python
"""Black Forest Labs (Flux) image adapter — async submit -> poll -> download; x-key auth."""
from __future__ import annotations
import base64, time
from typing import Any
from .._ratelimit import LIMITER
from ._auth import HeaderAuth
from ._http import parse_json, request
from .base import AdapterError, Output

_MEDIA_TYPE = "image/png"
_POLL_INTERVAL_S = 1.0            # monkeypatched to 0 in tests
_POLL_TIMEOUT_S = 300.0
_READY = "Ready"
_TERMINAL_FAIL = frozenset({"Error", "Request Moderated", "Content Moderated", "Task not found"})

def _client(base_url: str) -> Any:
    import httpx2
    return httpx2.Client(base_url=base_url, timeout=60.0)

def image_price(model: Any, size: str | None) -> float:
    return float(model.price.amount)   # pinned credits per image

def _parse_size(size: str | None) -> tuple[int, int]:
    if size and "x" in size:
        w, h = size.split("x", 1)
        return int(w), int(h)
    return 1024, 1024

def _submit_poll_download(client: Any, auth: Any, path: str, body: dict[str, Any]) -> Output:
    submit = request(client, "POST", path, provider="bfl", auth=auth, limiter=LIMITER, json=body)
    task_id = parse_json(submit, provider="bfl", where="submit")["id"]
    deadline = time.monotonic() + _POLL_TIMEOUT_S
    while True:
        if time.monotonic() > deadline:
            raise AdapterError("bfl", where="poll", detail="task timed out")
        # id is a task handle, not a secret; putting it in the query is fine (auth is the x-key header).
        poll = request(client, "GET", f"/v1/get_result?id={task_id}", provider="bfl",
                       auth=auth, limiter=LIMITER)
        payload = parse_json(poll, provider="bfl", where="poll")
        status = payload.get("status")
        if status == _READY:
            break
        if status in _TERMINAL_FAIL:
            raise AdapterError("bfl", where="poll", detail=f"status {status}")
        time.sleep(_POLL_INTERVAL_S)
    try:
        sample_url = payload["result"]["sample"]
    except (KeyError, TypeError) as exc:
        raise AdapterError("bfl", where="poll", detail="no result.sample in Ready response") from exc
    download = client.get(sample_url)            # signed URL, no auth header
    if download.status_code // 100 != 2:
        raise AdapterError("bfl", status=download.status_code, where="download",
                           detail="image download failed")
    return Output(data=download.content, media_type=_MEDIA_TYPE)

def generate(prompt: str, *, model: Any, provider: Any, size: str | None,
             secrets: dict[str, str]) -> Output:
    auth = HeaderAuth("x-key", secrets["BFL_API_KEY"])
    width, height = _parse_size(size)
    body: dict[str, Any] = {"prompt": prompt, "width": width, "height": height, "output_format": "png"}
    with _client(provider.base_url) as client:
        return _submit_poll_download(client, auth, f"/v1/{model.slug}", body)

def edit(image_bytes: bytes, prompt: str, *, model: Any, provider: Any, size: str | None,
         refs_bytes: list[bytes], secrets: dict[str, str]) -> Output:
    auth = HeaderAuth("x-key", secrets["BFL_API_KEY"])
    body: dict[str, Any] = {
        "prompt": prompt,
        "input_image": base64.b64encode(image_bytes).decode(),
        "output_format": "png",
    }
    for i, rb in enumerate(refs_bytes or [], start=2):   # extra refs -> input_image_2..4 (multiref)
        body[f"input_image_{i}"] = base64.b64encode(rb).decode()
    with _client(provider.base_url) as client:
        return _submit_poll_download(client, auth, f"/v1/{model.slug}", body)
```
The credential goes in the `x-key` header only (via `HeaderAuth`, applied by `request()`), never in a URL.

## Constraints / do-nots
- Create ONLY `sdk/sfvf/providers/bfl.py` and edit ONLY `sdk/sfvf/providers/registry.py`. Do NOT edit any
  test, the media.image surface, the openai adapter, or anything else.
- No `app.*` import; no new dependency (httpx2 lazy). No credential in a URL/query.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/providers/bfl.py`
- `sdk/sfvf/providers/registry.py`

## Verify (from the worktree; set `PYTHONPATH` to the worktree `sdk`)
- `-m pytest tests/integration/test_image_bfl.py -q` → all pass.
- `-m pytest tests/integration/test_image_openai.py tests/sdk/test_providers_registry.py -q` → still green.
- `-m pytest -q` (full) → green apart from the pre-existing HyperFrames/chrome env failures.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
