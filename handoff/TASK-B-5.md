# TASK B-5 — `media.video.generate` on Higgsfield REST (mocked HTTP; NO live call)

**Builder:** Cursor. **Product code only.** Create `sdk/sfvf/media/video.py` (new) and add `video` to
`sdk/sfvf/media/__init__.py`. You may add the `sfvf[openrouter]` httpx2 extra usage (already declared). Do NOT
touch `tests/`, `docs/`, `handoff/`, or other adapters. The reviewer contract
`tests/integration/test_video_higgsfield.py` is FROZEN.

Wire the **non-dry** path of `media.video.generate` to Higgsfield's documented REST API over `httpx2`,
exercised ENTIRELY against `httpx2.MockTransport` — **no live network call, no OAuth, no real key**. `dry_run`
is a genuine no-network stub: a real placeholder MP4 at zero cost.

## Higgsfield REST contract (verified from their OpenAPI)

- Base URL `https://api.higgsfield.ai`. Auth header: `Authorization: Key <secret>` where the secret is the
  full `"{api_key_id}:{api_key_secret}"` value (stored as one secret).
- **Submit:** `POST /<model>` (the `model` arg IS the path, e.g. `"sora-2/text-to-video"`), JSON body
  `{"prompt": ..., ...}` → `200` `RequestStatus`: `{request_id, status:"queued", status_url, cancel_url}`.
- **Poll:** `GET <status_url>` (the absolute URL from the submit response) → `RequestStatus` with
  `status ∈ {queued, in_progress, nsfw, failed, completed, canceled}`. Keep polling while `queued`/
  `in_progress`; terminal otherwise.
- **Result:** on `completed`, the finished clip is `video.url` (a `{"url": ...}` object). On
  `failed`/`nsfw`/`canceled`, use the `error` field.
- **Download:** `GET <video.url>` → the video bytes.

## Implement `sdk/sfvf/media/video.py`

Signature (SDK §6.3; returns a **video-relative path string** per §5.5, not a Path):

```python
generate(prompt, *, model, first_frame=None, last_frame=None, refs=None, duration_s=None, extra=None) -> str
```

Seams the frozen tests require (implement exactly):
- `def _http_client() -> httpx2.Client:` — module-level factory, **lazy-import httpx2**, returns
  `httpx2.Client(base_url="https://api.higgsfield.ai", timeout=<sane>)`; clear RuntimeError naming
  `sfvf[openrouter]` if httpx2 is absent. (Reuse the exact pattern from `sfvf/agents.py`.)
- `_LIMITER` — `from .._ratelimit import LIMITER as _LIMITER`, configured once for `"higgsfield"`.
- `_POLL_INTERVAL_S` — module constant (e.g. `2.0`; tests monkeypatch to `0.0`), the sleep between polls.
- `_POLL_TIMEOUT_S` — a large bounded cap (e.g. `1800.0`) so a stuck job can't poll forever.

Behaviour:
1. `ctx = current_context()` (unchanged raise with no active context).
2. **dry_run:** produce a placeholder MP4 with `sfvf._ffmpeg.color_bars(dest, duration_s=duration_s or <default
   e.g. 5.0>, width=1080, height=1920, fps=30)` at a content-addressed artifact path (reuse
   `graphics._artifact(ctx, f"video-{_sha8([...])}.mp4")` and `graphics._sha8`); return the video-relative
   string. **No secret read, no HTTP.** (frame/ref args are accepted and ignored in dry_run.)
3. **Non-dry:**
   - If any of `first_frame`, `last_frame`, `refs` is provided, raise `NotImplementedError`
     ("frame/ref-conditioned generation is not yet supported by the Higgsfield adapter") — this increment is
     text-to-video only. Do NOT silently ignore them.
   - `key = ctx.secret("HIGGSFIELD_API_KEY")` **before** building any client (missing key ⇒ KeyError, no call).
   - Build the body: `body = {"prompt": prompt}`; if `duration_s is not None`: `body["duration"] = duration_s`
     (best-effort mapping — see the HARDENING note the supervisor is filing); then `body.update(extra or {})`.
   - **Submit** inside `_LIMITER.slot("higgsfield")`: `client.post("/" + model, headers={"Authorization":
     f"Key {key}"}, json=body)`. Non-2xx ⇒ `RuntimeError(f"Higgsfield submit {status}: {resp.text}")`. Parse
     `request_id` and `status_url`.
   - **Poll loop** (deadline = now + `_POLL_TIMEOUT_S`): `GET status_url`; parse `status`; on `completed` break;
     on `failed`/`nsfw`/`canceled` raise `RuntimeError` including the `error`; otherwise
     `ctx.heartbeat("video", waiting_on="higgsfield")`, sleep `_POLL_INTERVAL_S`, and continue. On deadline
     exceeded raise a clear timeout `RuntimeError`. Emit at least one heartbeat per poll iteration (the frozen
     heartbeat test depends on it).
   - **Download:** `GET completed["video"]["url"]`; write the bytes to a content-addressed artifact
     (`graphics._artifact(ctx, f"video-{_sha8([prompt, model, duration_s, extra])}.mp4")`); return the
     video-relative string. The client key is never logged or put in an error message.
   - **Cost:** Higgsfield is credit-based and the status response carries no cost field; surface a `ctx.log`
     line with model + request_id (NO `t=="cost"` event — Stage C owns metering, HARDENING H10).
- `media/__init__.py`: add `video` to the imports and `__all__` (keep alphabetical).

mypy-strict clean. No new dependency (httpx2 is the existing `sfvf[openrouter]` extra; reuse it). Reuse
`graphics._artifact`/`_sha8` and `_ffmpeg.color_bars` — do not duplicate them.

## Acceptance

`tests/integration/test_video_higgsfield.py` passes (8 tests): dry-run returns a real placeholder MP4 with no
call; real submits (auth `Key`, model path, prompt) + polls to terminal + downloads and saves the bytes;
heartbeats while polling; a `failed` status raises; `extra` + `duration_s` land in the body; missing key raises
before any call; frame/ref conditioning raises `NotImplementedError`; no-active-context raises. Nothing else
regresses.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_video_higgsfield.py
```
(The full `pytest` run also shows 3 pre-existing `finalize`/`example_workflow` failures — ONLY the HyperFrames
toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
