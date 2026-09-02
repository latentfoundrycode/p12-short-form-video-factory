# Changes

A running log of notable changes outside the per-task build history.

## 2026-09-02 — A-6: `sfvf.finalize` — the mandatory last step

`finalize(video, audio=None, captions=None)` (SDK §6.9) is the required final call of every workflow. It
applies the house format with FFmpeg — H.264, the default vertical 1080×1920 @ 30fps, `-14` LUFS loudness —
muxing the optional narration and captions, and returns the finished file's video-relative path
(`"final.mp4"`). It is REAL in both dry and non-dry modes (FFmpeg is local/free), and reachable as both
`sfvf.finalize` and `media.finalize`. Its self-review is **structural** for now: the output must be a valid
file of the house resolution with the expected streams present (video always; audio iff narration given;
subtitles iff captions given), and a failure raises so the video is marked failed (SDK §3.4/§5.8). Input
paths are resolved-then-confined to the video folder (rejecting `..` escapes), matching the project's
path-confinement standard.

**Scoping decisions (recorded):**
- **Content self-review checks are DEFERRED to Stage E.** SDK §5.8's silence/clipping, black-frame and
  slideshow detection can't pass on dry-run stubs (silent audio, static colour-bars) and need real assets
  and the composition DOM. A-6 does the structural checks; the full §5.8 suite lands with records/review.
- **House format is fixed (not yet `[output]`-driven).** `[output]` (aspect/fps/safe_zone) is not in the
  runtime Context yet, so finalize uses the PRD default (vertical 1080×1920 @ 30). Per-`[output]` sizing is
  deferred, like `safe_zone_css`.

## 2026-09-02 — A-5: `sfvf.media.graphics` dry-run stubs (composition)

`sfvf.media.graphics` (SDK §6.5) is stubbed with FFmpeg while the real HyperFrames provider is deferred to
Stage B: `render(html, *, duration_s)` writes a colour-bars clip of the requested duration; `captions(audio,
timings, style)` writes a subtitle file from the word timings; `safe_zone_css()` writes a CSS file; and
`check(html, *, safe_zone=True)` reports no violations (`[]`). The file-producing functions return
**video-relative path strings** (JSON-native), so a `render` result caches through `ctx.step` and the file
is content-addressed by the step cache — extending the A-3/A-4 pattern. `render`/`captions`/`check` raise
`NotImplementedError` outside dry-run (HyperFrames is Stage B); `safe_zone_css` is format logic and returns
its CSS in both modes, using the PRD's authoritative reserved-region margins (top 10%, right 15%, bottom
15%). Filenames hash a JSON-serialised structured key (not naive concatenation) so distinct inputs never
collide onto one artifact — matching the SDK-1 cache canonicalisation invariant. No cost event (deferred to
Stage C). (Both refinements came from the cross-family reviewer: a 5% right margin would let content render
under the platform's buttons, and concatenated hash material could alias two distinct renders.)

## 2026-09-02 — A-4: `sfvf.media.speech` dry-run stub

The `sfvf.media` package appears, with `media.speech.speak(text, *, voice, model) -> Speech` (SDK §6.4). In
dry-run it writes silent audio of a plausible length (words ÷ speaking rate) into `ctx.artifacts` via the
FFmpeg core (A-1) and returns a `Speech` — a JSON-native TypedDict: `audio` (a video-relative path string),
`timings` (per-word `{word, start, end}` dicts spread across the clip), and `duration` (the real audio
length). JSON-native so the documented `step.set(speak(...))` caches (following the A-3 pattern; the audio
file is content-addressed by the step cache via its relative path). Deterministic in its inputs. The real
ElevenLabs adapter is Stage B, so the non-dry-run path raises `NotImplementedError`.

## 2026-09-02 — A-3: `sfvf.agents` dry-run stubs (LLM + research)

`sfvf.agents` (SDK §6.1) is now importable with `llm(prompt, *, agent, model, schema=None, attach=None)`
and `research(query) -> list[Source]`, plus the `Source` type. In dry-run they return deterministic free
stubs — placeholder text (or a shaped dict when a `schema` is asked for), and a canned list of `Source`s —
so a workflow's structure can be exercised at zero cost (SDK §10). They read the ambient Context (A-1) to
decide dry-run, so calling one outside a running workflow raises. The real OpenRouter adapter is Stage B,
so the non-dry-run path raises `NotImplementedError` rather than silently returning nothing.

**Scoping decision (recorded):** cost recording is DEFERRED to Stage C. SDK §10 says a dry run records what
it *would* have cost, but that needs the budget engine's meters and estimation (Stage C), which own the
cost/meter event schema. Inventing a cost event here would pre-commit a schema Stage C should define, so the
A-stage stubs return free stubs without emitting cost — recorded so the omission is deliberate, not missed.

**Design decision (recorded) — provided-function results are JSON-native.** SDK §5.5 requires step results
to be JSON-serializable ("return their paths relative to the video folder"), and the documented pattern
caches provided-function results via `ctx.step` (`step.set(agents.research(...))`). A rich attribute-access
object (dataclass) cannot round-trip through the JSON step cache without a type-reconstruction protocol —
a much larger SDK change. So provided-function return types are **JSON-native**: `Source` is a `TypedDict`
(a plain dict at runtime; subscript access `source["title"]`), and `research()`/structured `llm()` return
JSON-serializable data. This reconciles §5.5 with §6.1/§11.1's *illustrative* attribute-access pseudocode,
and sets the pattern the later media stubs (e.g. `Speech`, A-4) follow — a `Speech` result will likewise be
a TypedDict whose `audio` is a video-relative path string the cache stores by content. Flagged for the
owner at the Stage A/B boundary in case attribute-access rich types (with a serializer) are preferred.
(Found by the cross-family reviewer: raw dataclasses broke the documented `step.set(research(...))` cache
path; and the structured stub ignored the requested schema.)

## 2026-09-02 — A-2: the `Result` a workflow returns

`sfvf.Result` (SDK §3.3) is now a public type a workflow's `run()` returns to report its finished video:
`video` (Path, required) plus optional `caption`, `hashtags`, `cover_frame_s` (default 1.0), `notes`, and
`extra`. The SDK runner turns a returned `Result` into the `result` event the chassis already records,
with the video path made **relative to the video folder** (SDK §5.5), and the supervisor now persists the
**whole** Result into `video.json` (previously only `video`/`caption` survived) — so `extra` is recorded
verbatim (the basis for `ctx.previous` continuity) and `notes` reaches the detail view. An example
workflow's finished file therefore reaches `video.json` by returning it, rather than hand-emitting a
result event. Workflows that return `None` and emit their own event are unaffected (backward compatible).

## 2026-09-02 — Stage A begins; T1 (early HyperFrames/Kinocut) reversed

The remaining build order is settled as A→B→C→D→E→F→G (arch §7): **A** the provided-functions dry-run
stub layer + an example workflow + minimal finalize (zero cost); **B** real providers cheap→expensive;
**C** the budget engine; then library, records/review, gates, learning. Stage A is starting.

**Recorded decision — T1 reversed.** The accepted plan briefly pulled the HyperFrames and Kinocut
composition providers forward into Stage A (proposal "T1") on the assumption they were cheap local
drop-ins. They are not: they are existing **external** repositories integrated via an adapter, and
HyperFrames drags in a headless Chromium browser plus installed fonts that windows-latest CI cannot
easily exercise. The architecture's own build order (§7) homes them in the providers stage. So T1 is
dropped — Stage A ships a real, validated, zero-cost `.mp4` using the FFmpeg-based dry-run stub engine
(colour-bar visuals, silent audio of the right length), and HyperFrames/Kinocut move to Stage B where
their repos are investigated at source and wired through adapters. (Arch §5.5 was patched to state this
outright.)

## 2026-09-01 — SDK-4: context identity/reporting + dry-run (supervisor wiring)

Final increment of the SDK/step-mechanism stage (Workflow SDK §3.2, §4.1–§4.3, §5.9). The supervisor
now writes runtime identity and the content-addressed cache root into `context.json`, so a real run can
finally cache. `app/core/supervisor.py` gains a frozen `_ContextWiring` dataclass and a `_make_context`
factory that populate both the prepare context (`video_index=0`) and each per-video context with
`workflow_version`, `workflow_id`, `run_id`, `video_index`, `video_count`, `dry_run`, `step_concurrency`,
`paths.cache`, and `paths.workflow`. `run_request` gains three defaulted params (`cache_dir`, `dry_run`,
`step_concurrency`). `sdk/sfvf/context.py` exposes the §4.1 accessors (`ctx.workflow_id/run_id/
video_index/video_count/video_dir/shared_dir/workflow_dir/step_concurrency`), `ctx.dry_run`, and
`ctx.decision(...)`; `sdk/sfvf/emit.py` gains the `decision` emitter (`{"t":"decision","kind","chosen"
[,"alternatives"][,"reason"]}`). This also delivers the supervisor wiring deferred from SDK-2 (SDK-2b).

**Supervisor technical decisions (recorded):**
- **Cache root persists across runs, partitioned by workflow AND run mode:**
  `((cache_dir or CACHE_DIR)/workflow_id/{"dry"|"real"}).resolve()`. Per-workflow avoids family-name
  collisions (`step_key` keys on version+family+inputs, not `workflow_id`). The **dry/real split prevents
  a dry run's placeholder assets from poisoning the paid cache** — `step_key` omits `dry_run`, so without
  the mode segment a dry run and a real run of the same step+inputs would share one entry and a later real
  run would be served the fake asset and skip generation.
- **`dry_run`/`step_concurrency` added as defaulted `run_request` params.** They have no API/frontend
  source yet; defaulting them lets the supervisor write them now and wires cleanly when a caller opts in.
  Every new `ContextFile`/`ContextPaths` field is defaulted so existing `context.json` and callers stay
  valid.

**Gate note.** Review A (Claude Opus 4-8, Anthropic) APPROVED; the cross-family verifier (GPT-5.6 Sol,
OpenAI) REJECTED round 1 on the dry/real cache-sharing hazard — a legitimate correctness catch that
Review A approved past. Judged in-scope (this is the increment that introduces both `dry_run` and usable
cross-run caching) and fixed with the mode partition plus a third contract run that asserts a real run
never reuses the dry cache; both families APPROVED the round-2 diff. Gate green (176 passed, 1 skipped).
This was the only SDK-stage increment to use the one permitted re-delegation.

## 2026-09-01 — SDK-3: ctx.map, parallel steps of one family

Third increment of the SDK/step-mechanism stage (Workflow SDK §4.7). `sdk/sfvf/context.py` gains
`ctx.map(family, items, *, inputs, fn, label=None, concurrency=1, on_error="raise")`: each item runs
as a full `ctx.step` (inheriting caching, file handling, and the `step` event), across a
`ThreadPoolExecutor` bounded by `concurrency`, with results returned in INPUT order regardless of
completion order. `on_error="raise"` returns `list[value]` and propagates the first failure;
`on_error="collect"` returns `list[Outcome]` (`value`/`error`/`ok`). `sdk/sfvf/emit.py` now serializes
write+flush under a module lock so the concurrent `step` events cannot tear a line in `events.jsonl`.

**Supervisor technical decisions (recorded):**
- **`on_error="collect"` catches `Exception`, not `BaseException`.** The first attempt caught
  `BaseException`; the cross-family reviewer (GPT-5.6 Sol) flagged that this would swallow
  process-control signals (`SystemExit`/`KeyboardInterrupt`/`GeneratorExit`). Corrected to `except
  Exception` so those propagate; `Outcome.error` typed `Exception | None`. (The two reviewers split on
  this — Opus judged the broad catch "defensible" for worker threads, Sol rejected it; the fix is
  standard best practice and satisfies both.)
- **Cancellation-between-items DEFERRED.** §4.7's "cancellation is honoured between item completions"
  ties to the stop-sentinel mechanism, which is not wired at the SDK boundary yet. Deferred to a later
  increment; recorded so it is not mistaken for missing.

Both reviewers APPROVED the final diff; gate green (175 passed, 1 skipped).

## 2026-09-01 — SDK-2: ctx.step, the cached step boundary

Second increment of the SDK/step-mechanism stage. `sdk/sfvf/context.py` gains `ctx.step(family, *,
inputs, label=None)` — a context manager over the SDK-1 cache (Workflow SDK §4.5, §5.1-§5.5). On a
hit it returns the stored result and restores its files without running the body; on a miss it runs
the body, and `step.set(value)` stores the result plus any files the value names. It emits a `step`
event (`{t, name, key, label, status}`), the `label` is display-only (never in the key), and a body
that raises stores nothing. Two OPTIONAL context fields were added (`ContextPaths.cache`,
`ContextFile.workflow_version`, both defaulted so existing `context.json` still validates); the
supervisor does not populate them yet (SDK-2b wires that).

**Supervisor technical decisions (recorded):**
- **File paths are VIDEO-relative (SDK §5.5), not artifacts-relative.** The first attempt (and the
  original reviewer test) treated returned paths as relative to `ctx.artifacts`; the cross-family
  reviewer (GPT-5.6 Sol) caught that §5.5 makes them relative to the video folder. The spec settles
  it, so I corrected the test and implementation to derive/restore relative to `paths.video` — no
  escalation needed. (This is why files are written under `ctx.artifacts` but returned as e.g.
  `"artifacts/final.mp4"`.)
- **Known limitation (deferred, recorded):** a step whose result is literally `None` reads as a cache
  MISS, because SDK-1's `StepCache.get` uses `None` as its miss sentinel and `ctx.step` treats
  `found is not None` as the hit signal. The failure mode is a benign re-run (never a stale result),
  and no realistic step returns `None`. Closing it would be a `StepCache` API change (a distinct
  "exists" signal) — deferred; noted here so it is not rediscovered as a surprise.

Both reviewers APPROVED the final diff; gate green. (Process note: the reviewer test had two lint-only
reflows by the implementer — import grouping + a combined `with`, assertions unchanged — a consequence
of lint nits in the authored test; lesson recorded to lint contract tests before delegating.)

## 2026-09-01 — SDK-1: content-addressed step cache

First increment of the SDK/step-mechanism stage. Added `sdk/sfvf/cache.py`: `step_key(workflow_version,
family, inputs)` and a `StepCache` content-addressed store, per Architecture §5.9 and Workflow SDK
§5.2a/§5.3/§5.5. The key is a SHA-256 over the workflow version + family + inputs in a canonical form;
any `Path` in inputs (values or keys, nested) is hashed by file CONTENT, not path text; `label` is never
in the key. `StepCache` round-trips a JSON result plus files stored/restored by content, with atomic writes.

**Supervisor technical decisions (recorded):**
- **Scope.** A single content-addressed store. The paid/cheap partition and LRU eviction (§5.9) are
  deliberately DEFERRED to the budget-engine stage — they need per-step cost info that does not exist yet.
- **Canonicalization is unambiguous by construction.** Distinct input shapes get distinct markers so no
  two can collide in the key: a `Path` → `{"__sfvf_file_sha256__": <hex>}`, a `dict` →
  `{"__sfvf_dict__": [[k,v],… sorted]}`, a `list` stays a list. This closes a class of subtle
  wrong-cache-hit bugs (a string equal to a file digest; a dict vs a pair-shaped list).
- **Restore is path-confined to the project standard.** File restore refuses absolute/`..` names AND
  resolves each destination to verify it stays inside `restore_into` (`Path.is_relative_to`), so a
  pre-existing symlink cannot redirect a write outside it. This mirrors the file-server increment
  (005-3) — a consistency fix to the existing path-confinement standard, not new policy.

**Gate note.** This foundational primitive went through four cross-family review rounds: the decorrelated
verifier (GPT-5.6 Sol) surfaced progressively finer canonicalization/confinement edges that the
Anthropic reviewer approved past; each was fixed with a reviewer-authored test. The final round-3 finding
(dict vs pair-list) was esoteric on an otherwise-verified core; per the owner's guidance I judged it not a
stop and applied the terminal marker fix that closes the shape-ambiguity class by construction, rather
than accept it as a documented wart — keeping the two-reviewer gate intact (both APPROVE on the final diff).

## 2026-09-01 — CI action majors bumped to the Node-24 runtime

Bumped three GitHub Action majors in `.github/workflows/ci.yml` off the deprecated Node-20 action
runtime to their current Node-24 majors: `actions/checkout@v4→v5`, `actions/setup-node@v4→v7`, and
`actions/setup-python@v5→v6`. CI-config only — no product code, no test change; the gate steps,
`!cancelled()` guards, permissions, concurrency, and caching are unchanged, as is the frontend
`node-version: "20"` (the app runtime, separate from the action runtime) and `python-version: "3.12"`.

Run through the full gated loop: implemented by Cursor (Grok 4.6), Review A (diff-reviewer, Claude
Opus 4-8) APPROVE + Review B (GPT-5.6 Sol, read from a committed diff file per the hardened policy)
APPROVE, gate-integrity clean, auto-merged when the required `gate` check went green.

## 2026-09-01 — F2: hand out a run id only after request.json exists

Fixed a launch-window ordering race in `app/core/supervisor.py` (`run_request`): the
`on_started(run_id)` callback — how the run API learns the id it returns from `POST /runs` — fired
**before** `request.json` was written, so a client reading the run immediately after the 202 could
race a not-yet-written file and get a spurious 404. The single `on_started` call now fires only
**after** `create_request(...)` (and after the folder skeleton and `_runs` registration). Merged
via PR #8 (`abcecf9`).

This was the **first increment run through the full gated merge loop**: reviewer-authored test that
reproduced the race and failed on `main` → fix implemented by Cursor (Grok 4.6) → Review A
(diff-reviewer, Claude Opus 4-8) APPROVE + Review B (GPT-5.6 Sol) APPROVE → gate-integrity clean →
auto-merged (squash) when the required `gate` check went green.

## 2026-09-01 — Continuous integration (GitHub Actions)

Added `.github/workflows/ci.yml`. On pull requests targeting `main`, a **windows-latest** job
(the project is Windows-only and has Windows-specific tree-kill / process-group code paths that must
be exercised) installs the pinned dependencies — pip `requirements.txt` + `requirements-dev.txt`
(including the editable SDK and the `--no-binary mypy` line) and `npm ci` in `frontend/` — then runs
the full six-command gate, each as its own named step:

1. `ruff check`
2. `ruff format --check`
3. `mypy`
4. eslint (`npm run lint`)
5. tsc (`npm run typecheck`)
6. `pytest`

The six checks run with `if: ${{ !cancelled() && … }}` so a single CI run surfaces **every** failing
check at once (not one at a time), while remaining guarded on both install steps succeeding so a
setup failure hard-stops the job; any check failure fails the job. Versions are pinned explicitly
(Python **3.12**, Node **20** LTS) since the repo has no `.python-version` or Node engines pin. pip
and npm are cached via the setup actions.

### What the green CI check does NOT cover

Two gaps are inherent to the current test suite and are **not** exercised by CI (mirrored in
`docs/PROJECT_STATUS.md`):

- **Real environment-manager venv build.** `tests/core/test_env.py` mocks
  `find_python` / `create_venv` / `install`, so CI never builds a real per-workflow venv or runs pip
  into one. The real path (`python -m venv` + `pip install -e sdk`) was verified by hand during
  Task 6, not by CI.
- **Real-socket SSE streaming and frontend runtime behaviour.** The SSE tests use FastAPI's
  in-process `TestClient`, which buffers streamed responses — CI confirms event content, ordering,
  and stream close, but **not** live incremental delivery over a real socket (verified manually
  against a real uvicorn server). The frontend has **no unit-test runner**; CI covers it via eslint +
  tsc only (lint + types), not runtime behaviour (verified manually in a browser).

No tests are skipped, weakened, or disabled to make CI green — all 150 run.
