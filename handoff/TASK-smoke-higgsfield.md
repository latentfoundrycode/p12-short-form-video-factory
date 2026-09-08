# TASK — `smoke_higgsfield` workflow (minimal attended-first-run vehicle)

## Goal (one sentence)
Create the smallest workflow that makes ONE Higgsfield (Kling turbo) text-to-video call, so the
attended first real run can validate the live adapter + the budget breaker with a single generation —
mirroring `workflows/smoke_openrouter/` in shape.

## The frozen contract (already committed — do not edit the test)
`tests/integration/test_smoke_higgsfield.py` must pass:
- The workflow declares `requires_keys = HIGGSFIELD_API_KEY` (without it the §5.6 allowlist withholds
  the key and the real run dies with `KeyError` — the Speech-2b lesson).
- Running the workflow in `dry_run` end to end reaches `complete` and produces a video (the SDK stubs
  the Higgsfield call as a local colour-bars clip — no key, no HTTP, no spend).

## Create exactly three files under `workflows/smoke_higgsfield/`

### `workflow.toml`
Mirror `workflows/smoke_openrouter/workflow.toml`, with:
- `id = "smoke_higgsfield"`, `name = "Higgsfield Smoke"`, `version = "1.0.0"`, `entrypoint = "main:run"`, `sdk = "1"`.
- a `[[requires_keys]]` block: `name = "HIGGSFIELD_API_KEY"`, `label = "Higgsfield"`.

### `main.py`
A `run(ctx: Context) -> Result` that makes ONE text-to-video call and returns the clip as the Result:
- Model (the adapter's `model` arg is the API path after the base URL):
  `"kling-video/v2.5-turbo/pro/text-to-video"` — put it in a module constant `_MODEL`.
- Call `media.video.generate` (use the same import style the rest of the SDK uses for it — check how
  `media.video.generate` is imported/called elsewhere, e.g. `tests/integration/test_video_higgsfield.py`).
- Pass a short, unambiguously SFW prompt (e.g. a calm nature scene) — a prompt that trips the API's
  `nsfw` moderation status wastes the run.
- **Pass `extra={"aspect_ratio": "9:16"}`** so the clip is vertical short-form. Do NOT pass
  `duration_s` — omitting it lets the API default to its 5-second integer duration (the adapter maps
  `duration_s` to a float, which the API's integer-enum `duration` would reject; see HARDENING H25).
- Return `Result(video=ctx.video_dir / rel, caption="higgsfield smoke ok", extra={"model": _MODEL})`
  where `rel` is the video-relative path `generate` returns.
- Keep a short module docstring describing the purpose (mirror `smoke_openrouter/main.py`).

### `requirements.txt`
Just `httpx2==2.10.0` (the Higgsfield adapter's HTTP dependency — same as smoke_openrouter).

## Constraints / do-nots
- Do NOT modify `sdk/sfvf/media/video.py` (the adapter) — the duration/aspect issues are logged as
  H25 and deliberately sidestepped here. Do NOT touch any test or `budget.toml`.
- No live key, no network, no spend — the only real call happens later in the attended run.
- Match the surrounding workflow style; keep `ruff` and `mypy` clean.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/integration/test_smoke_higgsfield.py -q` → both tests pass.
- `-m ruff check .` and `-m mypy sdk app` → clean. (The workflow file isn't under sdk/app; still keep it ruff-clean: `-m ruff check workflows/smoke_higgsfield`.)
