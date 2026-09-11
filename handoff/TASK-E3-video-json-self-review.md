# TASK E-3 — record the self-review into video.json (§5.8)

## Goal (one sentence)
Make `finalize` gather all its §5.8 self-review results into one `self_review` event and emit it
(before raising on any failure), and make the supervisor capture that event into
`VideoRecord.self_review` — so every run's review, pass or fail, is inspectable in `video.json`.

## Governing spec (verbatim — Architecture §5.8)
> Failure marks the video failed rather than presenting it. All results are written into
> `video.json`, so a borderline case can be inspected afterwards.

## Frozen contract (already committed — do NOT edit any test or stub)
- `tests/sdk/test_finalize_self_review.py` — finalize emits exactly one `{"t":"self_review", …}`
  event with the shape below, on success AND before raising on failure; `content` is null in a dry run.
- `tests/core/test_self_review_recording.py` (+ stubs `tests/stubs/emits_self_review`,
  `tests/stubs/leaks_self_review_secret`) — the supervisor records the event into
  `VideoRecord.self_review` (the event minus its `t` tag), records no block when none is emitted, and
  redacts an injected secret in the block.

The `VideoRecord.self_review: dict | None` field and `"self_review"` in `VIDEO_OPTIONAL_FIELDS`
already exist in `app/core/records.py` — do NOT change records.py.

## The self_review event shape (freeze exactly)
```json
{
  "t": "self_review",
  "passed": <bool>,                          // true iff failures == []
  "structural": {"duration_s": <float>, "width": <int>, "height": <int>,
                 "has_audio": <bool>, "has_captions": <bool>},
  "content": {"black": <bool>, "silent": <bool>, "clipping": <bool>, "slideshow": <bool>,
              "audio_mean_dbfs": <float|null>, "audio_peak_dbfs": <float|null>,
              "motion_score": <float>} | null,   // null in a dry run (content review skipped)
  "composition": {"checked": <int>, "violations": [{"kind": <str>, "detail": <str>}, ...]},
  "failures": [<str>, ...]                   // the hard failures that fail the video
}
```

## What to implement

### 1. `finalize` gathers + emits the self-review (`sdk/sfvf/finalize.py`)
Restructure `_self_review` so it COLLECTS results and failures instead of raising per check, then
emits once and raises once:
- **structural**: probe `dest` → `duration_s`, `width`, `height`, `has_audio`; `has_captions` from
  the existing `_has_subtitle`. The existing structural mismatches (wrong resolution, duration ≤ 0,
  audio/subtitle stream present/absent vs expected) become entries appended to `failures` rather than
  immediate raises. If `dest` is missing or has no video stream (cannot be probed at all), emit a
  minimal self_review (`passed:false`, the failure in `failures`, `structural`/`content`/`composition`
  best-effort) and then raise — do not skip the emit on that path.
- **content**: on a real run, run the existing `content_review(dest, expect_audio=expect_audio)` and
  fill `content` from its fields (`black`/`silent`/`clipping`/`slideshow`/`audio_mean_dbfs`/
  `audio_peak_dbfs`/`motion_score`); append its `failures` to the failures list. In a **dry run**,
  set `content` to `null` and run no content review (unchanged E-1 behavior).
- **composition**: reuse the existing composition-review discovery (glob `artifacts/render-*.html`,
  run `media.graphics.check(html, safe_zone=True)` on each — the E-2b behavior, both modes). Set
  `composition = {"checked": <#sidecars>, "violations": [<every violation dict>]}` and append each
  as a `f"composition: {kind}: {detail}"` entry to `failures`.
- Build the event dict, set `passed = not failures`, and `current_context().emit({"t": "self_review",
  **payload})` — **before** any `raise`. Then, if `failures` is non-empty, raise `RuntimeError` as
  today (keep the existing "finalize self-review failed: …" / "finalize composition self-review
  failed: …" messages; the frozen finalize/composition tests still match on them).
- Keep the house-format step and `finalize`'s return value unchanged.

### 2. The supervisor captures it (`app/core/supervisor.py`)
In `_consume_stdout`, alongside the `result` capture, capture the self_review from the **redacted**
event: `if event.get("t") == "self_review": self_review = {k: v for k, v in redacted.items() if k !=
"t"}` (so it is secret-redacted for free, like `cost`/`result`). Return it as an added element of the
tuple. Update BOTH call sites of `_consume_stdout` for the new arity (the prepare/shared call ignores
it; the per-video call uses it). In the per-video `write_video(... VideoRecord(...))`, add
`self_review=<captured>` — recorded **regardless of status** (a *failed* video's review is exactly
what §5.8 wants inspectable, so do NOT gate it on `status == "complete"` the way `result` is).

## Constraints / do-nots
- Do NOT edit any test or stub, change the frozen event shape, or change `app/core/records.py`.
- Do NOT change `finalize`'s signature/return, the house-format step, or E-1/E-2 verdict logic —
  only gather their results and emit before raising.
- No new dependencies. Keep `ruff`, `ruff format`, and `mypy --strict` clean; match the surrounding
  style.

## Scope
- `sdk/sfvf/finalize.py`
- `app/core/supervisor.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_finalize_self_review.py tests/core/test_self_review_recording.py -q` → all pass.
- `-m pytest tests/sdk/test_finalize.py tests/sdk/test_content_review.py tests/core/test_cost_recording.py tests/core/test_result_persistence.py tests/integration/test_finalize_composition_check.py -q` → green.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
