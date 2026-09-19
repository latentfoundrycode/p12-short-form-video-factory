# TASK — P-4: media.video router + BytePlus Seedance adapter

## Goal (one sentence)
Turn `media.video.generate` into a registry router (legacy Higgsfield slug → the existing inline path,
kept working; a registered video model → its adapter), add the BytePlus Seedance adapter and a shared
local-file→URL reference bridge, and register the deprecated `higgsfield` row + the Seedance model — so the
frozen contract goes green AND `tests/integration/test_video_higgsfield.py` stays green, unchanged.

## Spec (docs/PROVIDER_LAYER_PLAN.md §3.4; BytePlus API pinned in docs/PROJECT_STATUS.md) — authoritative
BytePlus ModelArk Seedance is ASYNCHRONOUS: `POST /contents/generations/tasks` with a `content` array →
`{"id":...}`; poll `GET /contents/generations/tasks/{id}` until `status=="succeeded"`; download the MP4 at
`content.video_url`. Cost is METERED from `usage.total_tokens`. Reference/frame images cross to the provider
as URLs; the local-file→URL bridge is SFVF-core (a shared helper), not per-workflow: an already-`http(s)`
value passes through; a local video-relative path is inlined as `data:<mime>;base64,...`.

## Frozen contracts (already committed — do NOT edit)
- `tests/integration/test_video_byteplus.py` — make it pass.
- `tests/integration/test_video_higgsfield.py` — must stay **byte-for-byte green**. It monkeypatches
  `media.video._http_client` and `media.video._POLL_INTERVAL_S`, expects `KeyError` (missing key),
  `RuntimeError` (submit/poll/download failure), `NotImplementedError` (first_frame/last_frame/refs on the
  legacy model), `RuntimeError` (no active context), and the `extra`/`duration` passthrough — all on the
  legacy Higgsfield path. Preserve every one of those.
- `tests/sdk/test_providers_registry.py` — already updated by the supervisor for the new provider count.

## Import-weight rule
`import sfvf.providers.byteplus` and `sfvf.providers._refs` need stdlib only at module top; lazy-import
`httpx2` inside the call.

## What to create / change

### 1. `sdk/sfvf/providers/_refs.py` (new) — the shared reference→URL bridge (SFVF core)
```python
"""Turn a workflow-supplied reference/frame (a video-relative file OR an http(s) URL) into a URL a
provider can fetch. Local files inline as a data URI (option 1); http(s) passes through. This is
chassis-level and shared by every video adapter, never handled per workflow."""
from __future__ import annotations
import base64, mimetypes
from typing import Any

def image_ref_url(ctx: Any, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    data = (ctx.paths.video / path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
```

### 2. `sdk/sfvf/providers/registry.py` — add the deprecated Higgsfield row + the Seedance model
Add to `PROVIDERS`:
```python
"higgsfield": Provider(
    "higgsfield", "Higgsfield (deprecated)", ("HIGGSFIELD_API_KEY",), "higgsfield",
    "credit", "credits", "https://api.higgsfield.ai", "higgsfield",
    legacy_slugs=frozenset({"sora-2/text-to-video", "kling-video/v2.5-turbo/pro/text-to-video"}),
),
```
Add to `MODELS`:
```python
"byteplus/seedance-2.5": Model(
    id="byteplus/seedance-2.5", provider="byteplus", slug="dreamina-seedance-2-5-260628",
    kind="video", capabilities=frozenset({"video.generate", "video.refs", "video.first_frame"}),
    label="BytePlus Seedance 2.5",
    price=PriceHint(unit="usd", basis="per_1m_tokens", amount=10.70, verified="2026-09-19"),
    notes="metered per 1M video tokens; the real rate is confirmed at the attended live smoke",
),
```
(The `higgsfield` row's `adapter="higgsfield"` is nominal — the router runs the legacy path INLINE and
never imports a `higgsfield` module, and `higgsfield` has no models so the capable-model→adapter guard
never looks for it.)

### 3. `sdk/sfvf/providers/byteplus.py` (new) — the Seedance adapter
```python
"""BytePlus ModelArk Seedance adapter — async submit -> poll -> download, metered cost."""
from __future__ import annotations
import time
from typing import Any
from .._ratelimit import LIMITER
from ._auth import BearerAuth
from ._http import parse_json, request
from .base import AdapterError, Cost, Output

_POLL_INTERVAL_S = 5.0            # monkeypatched to 0 in tests
_POLL_TIMEOUT_S = 1800.0
_EST_TOKENS_PER_S = 50_000        # rough pre-call reserve basis (actual reconciles from real usage)
_TERMINAL_FAIL = frozenset({"failed", "canceled"})

def _client(base_url: str) -> Any:
    import httpx2
    return httpx2.Client(base_url=base_url, timeout=60.0)

def video_estimate(model: Any, duration_s: float | None, extra: dict[str, Any] | None) -> float:
    return model.price.amount * _EST_TOKENS_PER_S * (duration_s or 5.0) / 1_000_000

def generate_video(prompt: str, *, model: Any, provider: Any, first_frame_url: str | None,
                   last_frame_url: str | None, ref_urls: list[str], duration_s: float | None,
                   extra: dict[str, Any] | None, secrets: dict[str, str], ctx: Any) -> tuple[Output, Cost]:
    auth = BearerAuth(secrets["BYTEPLUS_ARK_API_KEY"])
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if first_frame_url:
        content.append({"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"})
    if last_frame_url:
        content.append({"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"})
    for url in ref_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    body: dict[str, Any] = {"model": model.slug, "content": content}
    if duration_s is not None:
        body["duration"] = int(round(duration_s))
    body.update(extra or {})      # ratio / resolution / seed / watermark / generate_audio passthrough
    with _client(provider.base_url) as client:
        submit = request(client, "POST", "/contents/generations/tasks", provider="byteplus",
                         auth=auth, limiter=LIMITER, json=body)
        task_id = parse_json(submit, provider="byteplus", where="submit")["id"]
        deadline = time.monotonic() + _POLL_TIMEOUT_S
        while True:
            if time.monotonic() > deadline:
                raise AdapterError("byteplus", where="poll", detail="task timed out")
            poll = request(client, "GET", f"/contents/generations/tasks/{task_id}",
                           provider="byteplus", auth=auth, limiter=LIMITER)
            payload = parse_json(poll, provider="byteplus", where="poll")
            status = payload.get("status")
            if status == "succeeded":
                break
            if status in _TERMINAL_FAIL:
                raise AdapterError("byteplus", where="poll", detail=f"task {status}")
            ctx.heartbeat("video", waiting_on="byteplus")
            time.sleep(_POLL_INTERVAL_S)
        try:
            video_url = payload["content"]["video_url"]
        except (KeyError, TypeError) as exc:
            raise AdapterError("byteplus", where="poll", detail="no video_url in result") from exc
        download = client.get(video_url)          # signed/public URL, no auth header
        if download.status_code // 100 != 2:
            raise AdapterError("byteplus", status=download.status_code, where="download",
                               detail="video download failed")
        data = download.content
    total_tokens = float((payload.get("usage") or {}).get("total_tokens") or 0.0)
    amount = total_tokens / 1_000_000 * model.price.amount
    return Output(data=data, media_type="video/mp4"), Cost(amount=amount, source="metered")
```

### 4. `sdk/sfvf/media/video.py` — the router (refactor, keeping the Higgsfield path intact)
Keep ALL existing Higgsfield module-level names the frozen test relies on: `_http_client`,
`_POLL_INTERVAL_S`, `_POLL_TIMEOUT_S`, `_TERMINAL_ERRORS`, the `_WIDTH/_HEIGHT/_FPS/_DEFAULT_DURATION_S`
constants, and the `color_bars`/`_artifact`/`_sha8` imports. Extract the current Higgsfield body of
`generate()` verbatim into a helper `_higgsfield_generate(ctx, prompt, *, model, first_frame, last_frame,
refs, duration_s, extra, dest, rel) -> str` — same order and behaviour: raise `NotImplementedError` when
`first_frame`/`last_frame`/`refs` is not None (BEFORE reading the key), read `ctx.secret("HIGGSFIELD_API_KEY")`
(KeyError before any HTTP), `ctx._budget_reserve("higgsfield", "credits")`, submit `"/" + model`, poll,
download to `dest`, `ctx.log(...)`, return `rel`. Then:
```python
import importlib
from ..providers import CapabilityError, resolve
from ..providers._refs import image_ref_url

def generate(prompt, *, model, first_frame=None, last_frame=None, refs=None,
             duration_s=None, extra=None) -> str:
    ctx = current_context()                                  # RuntimeError if no active context
    dest, rel = _artifact(ctx, f"video-{_sha8([prompt, model, first_frame, last_frame, refs, duration_s, extra])}.mp4")
    if ctx.dry_run:
        color_bars(dest, duration_s=duration_s or _DEFAULT_DURATION_S, width=_WIDTH, height=_HEIGHT, fps=_FPS)
        return rel
    provider, mdl = resolve(model)
    if provider.id == "higgsfield":                          # legacy inline path (unchanged behaviour)
        return _higgsfield_generate(ctx, prompt, model=mdl.slug, first_frame=first_frame,
                                    last_frame=last_frame, refs=refs, duration_s=duration_s,
                                    extra=extra, dest=dest, rel=rel)
    if mdl.kind != "video" or "video.generate" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} cannot generate video")
    if refs and "video.refs" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} does not support reference conditioning")
    if (first_frame or last_frame) and "video.first_frame" not in mdl.capabilities:
        raise CapabilityError(f"model {model!r} does not support first/last-frame conditioning")
    secrets = {n: ctx.secret(n) for n in provider.secret_names}     # KeyError before any HTTP
    first_url = image_ref_url(ctx, first_frame) if first_frame else None
    last_url = image_ref_url(ctx, last_frame) if last_frame else None
    ref_urls = [image_ref_url(ctx, r["path"]) for r in (refs or [])]
    adapter = importlib.import_module(f"sfvf.providers.{provider.adapter}")
    estimate = adapter.video_estimate(mdl, duration_s, extra)
    token = ctx._budget_reserve(provider.meter, provider.unit, estimate=estimate)
    out, cost = adapter.generate_video(prompt, model=mdl, provider=provider, first_frame_url=first_url,
                                       last_frame_url=last_url, ref_urls=ref_urls, duration_s=duration_s,
                                       extra=extra, secrets=secrets, ctx=ctx)
    dest.write_bytes(out.data)
    ctx.record_cost(provider.meter, provider.unit, cost.amount, cost.source, token=token)
    return rel
```
Order: `current_context()` → dry_run → resolve → (higgsfield inline | capability checks → secrets →
ref→URL → reserve → adapter → artifact → record_cost). The capability checks and the secret read happen
BEFORE any HTTP, so the `test_refs_on_a_model_without_the_capability` and `missing_key` contracts see
`seen == []`. (`resolve` for a legacy slug returns the `higgsfield` provider + a synthesized model whose
`slug` is the bare slug, so `_higgsfield_generate` posts `"/" + "sora-2/text-to-video"` exactly as before.)

## Constraints / do-nots
- Create/edit ONLY: `sdk/sfvf/providers/_refs.py` (new), `sdk/sfvf/providers/byteplus.py` (new),
  `sdk/sfvf/providers/registry.py`, `sdk/sfvf/media/video.py`. Do NOT edit any test or other file.
- `tests/integration/test_video_higgsfield.py` MUST pass unchanged — verify it explicitly.
- No `app.*` import; no new dependency (httpx2 lazy). No credential in a URL/query.
- Keep `ruff check .`, `ruff format --check .`, `mypy` clean; ≤100 cols.

## Scope
- `sdk/sfvf/providers/_refs.py`
- `sdk/sfvf/providers/byteplus.py`
- `sdk/sfvf/providers/registry.py`
- `sdk/sfvf/media/video.py`

## Verify (from the worktree; set `PYTHONPATH` to the worktree `sdk`)
- `-m pytest tests/integration/test_video_byteplus.py tests/integration/test_video_higgsfield.py -q` → all pass.
- `-m pytest tests/sdk/test_providers_registry.py tests/sdk/test_providers_kit.py tests/integration/test_image_openai.py -q` → still green.
- `-m pytest -q` (full) → green apart from the pre-existing HyperFrames/chrome env failures.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
