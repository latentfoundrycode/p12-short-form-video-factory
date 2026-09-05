# Changes

A running log of notable changes outside the per-task build history.

## 2026-09-05 — S2b: stop exposing injected secrets (block context.json download + scrub post-run)

Closes the two exposure vectors a decorrelated security review flagged after S2a began injecting allowlisted
secrets into `context.json`: (1) the run-file download endpoint (`get_run_file`) now returns **404 for any
`context.json`** at any depth, so provider keys can't be pulled over HTTP (ordinary run files still serve);
(2) `_scrub_context_secrets` blanks the `secrets` in each on-disk `context.json` **after** its subprocess has
consumed it (in the `finally` of `_run_prepare` and `_run_one_video`, so it also runs on stop/failure), so the
keys don't persist in the run directory. Timing is post-`proc.wait()` — the workflow still reads its real
secrets during the run. No new secret handling; nothing logged. With S1 + S2a + S2b, the §5.6 secret path is
closed end-to-end (encrypted store → least-privilege injection → passphrase never in a child env → not
downloadable → scrubbed after use). Next: S2c (redact secret values from records/logs/errors) then T2.

Review resolution: the run-file endpoint's `context.json` block is airtight against NTFS alternate-data-stream
paths (verified empirically — `Path.resolve()` normalizes `context.json::$DATA` so the name guard catches it,
and `context.json:$DATA` is `is_file()==False` → 404; a flagged ADS bypass did not hold). The scrub was hardened
to run in a `finally` wrapping the spawn, so a runner-spawn failure can't leave un-scrubbed secrets on disk.

## 2026-09-05 — S2a: least-privilege secret injection + strip passphrase from all subprocesses

Wires the §5.6 store (S1) into the run pipeline. `create_app(..., secrets=None)` loads the `SecretStore` at app
start from `SFVF_SECRETS_PASSPHRASE` (+ `SFVF_SECRETS_PATH`) — empty when the passphrase is unset (dry runs need
no store); a wrong passphrase fails fast at startup — and holds the decrypted mapping on `app.state.secrets`.
Admission threads it (mirroring `ensure_env`/`popen`) into the run. **Least privilege:** each run's
`context.json` receives ONLY the secrets the workflow declares via the manifest `[[requires_keys]]` allowlist —
never the whole store (a compromised workflow can't reach unrelated providers' credentials). A new shared
`app.core.secrets.subprocess_env()` (os.environ minus `SFVF_SECRETS_PASSPHRASE`) is applied to **every** child
process the app spawns — the workflow runner AND the env-setup / `pip install` subprocesses in `env.py`
(HARDENING **H17**, incl. the HIGH finding that workflow-declared dependency builds could otherwise read the
master passphrase). No value or passphrase is logged. Next (S2b): keep `context.json` out of the run-file
download endpoint + scrub it after the runner reads it, and redact secret values from records/logs/errors.

## 2026-09-05 — S1: §5.6 encrypted secret store + CLI (first live-path prerequisite)

New `app/core/secrets.py`: `SecretStore(path, passphrase)` holds provider keys encrypted at rest —
`cryptography` Fernet with a key derived from the passphrase via scrypt over a random salt; the whole
name/value dict is encrypted (nothing plaintext on disk), the passphrase is never stored, and a wrong
passphrase raises `SecretsError` (fails loudly, no value leaked). A `python -m app.core.secrets` CLI provides
`set <NAME>` (reads the value via `getpass`, never echoed or on the command line), `list` (names only), and
`delete <NAME>`; passphrase from `SFVF_SECRETS_PASSPHRASE`, path from `SFVF_SECRETS_PATH`. **This is how a
human places real provider keys** (OPENROUTER_API_KEY / HIGGSFIELD_API_KEY) — no key is handled in the build.
Adds the `cryptography==50.0.1` app dependency (native binding verified not SAC-blocked). `ruff.toml`
`tests/**` gains `S105`/`S106` ignores (test fixtures for a secret store use hardcoded fake passphrases —
scoped to tests, product scanning unchanged). Next (S2): load the store at app start and inject permitted
secrets into `context.json` + redact secret values from records/logs/errors.

## 2026-09-05 — B-5: `media.video.generate` on Higgsfield REST (mocked HTTP; no live call)

New `sdk/sfvf/media/video.py`: `media.video.generate(prompt, *, model, ...) -> str` on Higgsfield's documented
REST API (Architecture §5.5 amended to REST/API-key — Option B). Async lifecycle over `httpx2`: submit
`POST /<model>` with `Authorization: Key <secret>` → `{request_id, status_url}`; poll `GET /requests/{id}/status`
(`queued`/`in_progress` → keep going; `completed` → `video.url`; `failed`/`nsfw`/`canceled` → error),
**heartbeating each poll** (§2.8/§6.3) with a bounded `_POLL_TIMEOUT_S`; download `video.url` → content-addressed
artifact → video-relative path. Reuses `ctx.secret` (§5.6, `HIGGSFIELD_API_KEY` = `"id:secret"`), the §5.5
`RateLimiter` (`higgsfield` queue), the `httpx2` `sfvf[openrouter]` extra, and `graphics._artifact`/`_sha8`.
`dry_run` is a genuine no-network stub: a real placeholder MP4 via `_ffmpeg.color_bars` at zero cost. Exercised
entirely against `httpx2.MockTransport` — **no live call, no OAuth, no real key**. **Scope: text-to-video**;
frame/ref-conditioned generation raises `NotImplementedError` (deferred). Cost surfaced via `ctx.log`, no cost
event (Stage C, H10). This is the last paid provider in dry_run/mocked form; the live-key boundary (a real
Higgsfield API key) is next and NOT built.

## 2026-09-05 — H7 fix: atomic-record I/O resilient to the Windows replace/open race

`app/core/records.py` now retries `write_json_atomic`'s `os.replace` and `read_json`'s `read_text` on a
transient `PermissionError` (bounded: `_RETRY_ATTEMPTS`×`_RETRY_DELAY_S`, then re-raise). On windows-latest,
an in-flight atomic record swap and a concurrent record read collide as a file-sharing violation
(`PermissionError [Errno 13]`) on either side; the swap completes in microseconds, so a small bounded retry
removes it. This is the fix for HARDENING **H7** — the app-layer subprocess/file-contention CI flake that
blocked CI three times (`test_runs`, `test_run_events`, `test_supervisor`, all `PermissionError` on
`request.json`/`video.json`). No behaviour change on the happy path; the temp file is still cleaned up when the
retries are exhausted. Not weakening — it makes the record I/O correct under Windows file-sharing semantics.

## 2026-09-03 — B-4d: real `agents.research` over OpenRouter web search (mocked HTTP; no live call)

The **non-dry** path of `agents.research` now uses OpenRouter's **web plugin** (`plugins:[{"id":"web"}]`) on a
pinned default model (research takes no model argument; §6.1 wants a named model for reproducibility) and maps
the web results — returned as `choices[0].message.annotations` `url_citation` objects (`url`/`title`/`content`)
— to `Source{title, url, snippet}` (an empty list when there are none). It reuses B-4c's HTTP plumbing, now
extracted into a shared `_post_chat_completion(ctx, body)` helper (auth, `_LIMITER` queue, bounded retry with
validated Retry-After, 402/429/error handling) that both `llm` and `research` call — `llm`'s behaviour is
unchanged. Exercised entirely against `httpx2.MockTransport`: **no live network call**. `dry_run` stays the
deterministic canned-`Source` stub. Cost is surfaced via `ctx.log` (no cost event — Stage C owns the meter
schema, HARDENING H10). This completes the OpenRouter agents surface (llm + research) in dry_run/mocked form;
the live-key boundary (encrypted store + real key) is next and NOT built.

## 2026-09-03 — B-4c: real `agents.llm` over OpenRouter (mocked HTTP; no live call)

The **non-dry** path of `agents.llm` now calls OpenRouter's chat-completions API (`httpx2`, added as the
optional `sfvf[openrouter]` extra), exercised entirely against an `httpx2.MockTransport` — **no live network
call is made anywhere**. `dry_run` is unchanged: a deterministic stub, no secret read, no HTTP. The real path
reads the bearer token via `ctx.secret("OPENROUTER_API_KEY")` (a missing key fails before any request), sends
`{model, messages}` (plus `response_format: json_schema` when a `schema` is requested — returning a parsed
dict), and queues behind the §5.5 `RateLimiter` (`_LIMITER.slot("openrouter")`). Errors: **429** honors
`Retry-After` via `_LIMITER.penalize` and retries (bounded); **402** is terminal (insufficient credits);
others raise with status + body. Vision `attach` in non-dry raises rather than being silently ignored (§6.1);
agent-rules injection is deferred to a later increment. `usage.cost` is parsed and surfaced in a `ctx.log`
line, but **no cost event is emitted** — the budget-engine cost/meter schema is Stage C's (HARDENING H10).
`research` keeps its dry-stub (its real OpenRouter path is the next increment). This is the last piece before
the live-key boundary: a live call needs the encrypted secret store + a real key, neither built here.

## 2026-09-03 — B-4b: per-provider rate-limiter scaffolding (§5.5)

New internal module `sdk/sfvf/_ratelimit.py`: a `RateLimiter` holding **one queue per provider** so a
provider's own caps are respected however many steps run at once (§5.5, §3.1a). `slot(provider)` acquires a
per-provider concurrency permit (`threading.Semaphore(max_concurrency)`) and paces successive requests by a
configurable `min_interval_s`; `penalize(provider, retry_after_s)` records a server-sent `Retry-After` back-off
as `not_before = max(not_before, now + retry_after_s)` (the **max**, never the sum). Providers are independent.
A module-level `LIMITER` instance is what the provider adapters (OpenRouter next) route through. Timing goes
through an injectable `monotonic`/`sleep` so it is deterministically testable. Scaffolding only — no adapter
code, no network. This is the §5.5 primitive the OpenRouter and (later) Higgsfield adapters queue behind.

## 2026-09-03 — B-4a: `ctx.secret(name)` accessor (SDK-side secrets read, §5.6)

First, smallest piece of the OpenRouter provider work: `Context.secret(name) -> str` reads a permitted secret
from the ambient `context.json`'s `secrets` dict — the accessor the provider adapters pull their bearer token
through (the SDK spec's `ctx.secret("OPENROUTER_API_KEY")`). A missing key raises `KeyError(name)`; the error
names only the key and never leaks a value, and the accessor never logs or otherwise exposes the returned
secret. **Deliberately only the read accessor** — the encrypted secret store, the passphrase prompt, and the
injection of a real key into `context.json` (§5.6 app-layer) are the live-key boundary and are NOT built here.
In tests the fake key lives only in an in-memory `ContextFile`; nothing is written to disk and no key is real.

## 2026-09-03 — B-2: `media.edit` (trim + cut) on real Kinocut

`sfvf.media.edit` lands as a real adapter over **Kinocut**'s local/free, FFmpeg-backed programmatic `Client`
(`KyaniteLabs/kinocut`, PyPI `kinocut==1.15.1`, Apache-2.0, no account/key, nothing uploaded). Per SDK §10 it
runs **REAL in both dry and non-dry modes** — `dry_run` means "no paid spend", not "no editing" — so like
`graphics.render` and `finalize` it produces real output at zero cost with no live keys. Scope this increment:
`trim(video, start, end)` → `Client.trim(start=, end=)` and `cut(clips, *, transitions=None)` →
`Client.merge(transitions=)`. Both take **video-relative** path strings, resolve them against
`ctx.paths.video`, run Kinocut writing a content-addressed `edit-trim-<sha>.mp4` / `edit-cut-<sha>.mp4` under
`ctx.paths.artifacts`, and return the result **video-relative** (POSIX) so it survives the JSON step cache
(§5.5) — mirroring the `graphics.render` conventions. `mix`/duck (§6.6) is intentionally **deferred** until a
workflow needs audio mixing (Kinocut splits it into `audio_compose` vs. `audio_bed` sidechain ducking, the
fiddliest mapping — not built ahead of need).

**Sourcing (Option A):** Kinocut is a pinned PyPI dependency — nothing cloned or vendored. It is an
**optional SDK extra** (`sfvf[edit] = ["kinocut==1.15.1"]`), lazy-imported by the adapter with a clear install
error if absent, because its core drags a heavy transitive stack (the MCP server: `mcp`/`starlette`/`uvicorn`/
`cryptography`/`pywin32`, ~28 packages) that has no place in lean core/production SDK installs — the same
"heavy toolchain stays out of the base" stance as HyperFrames. The pins resolve cleanly against the app's
locked set (verified: `fastapi==0.141.1`/`uvicorn==0.52.3`/`pydantic==2.13.4` all hold; Kinocut's constraints
`pydantic>=2.13.2`/`mcp<2,>=1.27.0`/`rich>=15` are loose, and the ML extras (torch/whisper/opencv/onnxruntime)
are not installed). The Kinocut Python `Client` API was pinned by introspecting the installed 1.15.1 package
(methods return a pydantic `EditResult` with `.output_path`), not from hypothesised docs.

**CI:** `kinocut==1.15.1` added to `requirements-dev.txt` (the gate/test env), so the gate installs it
alongside the already-present FFmpeg and the `tests/integration/test_edit.py` contract RUNS on windows-latest
rather than skipping. `mypy.ini` ignores missing imports for `kinocut.*` (it ships no `py.typed`).

**Recorded review calls (both families; supervisor split-verdict resolution).** (1) A scaffolding defect the
supervisor introduced and then corrected: the frozen `test_edit_requires_active_context` originally asserted
`LookupError`, but `current_context()` raises `RuntimeError` and every other SDK adapter (graphics/agents/
finalize) asserts `RuntimeError`. Both reviewers flagged the contract change; it is the **supervisor's**
deliberate correction (a separate commit from the builder's product-code commit, which touches only
`edit.py`/`__init__.py`), aligning the contract with the SDK convention — not a weakening. (2) The
cross-family reviewer raised that `trim`/`cut` block synchronously while Kinocut runs FFmpeg and emit **no
heartbeats**, so the supervisor's 300s silence watchdog (§2.8) could kill a legitimately long operation, as
`graphics.render` heartbeats. Resolved as **deferred, not blocking**: the merged `finalize` (A-6) — the direct
precedent, a blocking local FFmpeg encode of the whole video — also does not heartbeat, so this is not an
invariant the gate enforces; `render` heartbeats specifically because HyperFrames is a browser subprocess with
a known ~45s stall. Fixing `edit` alone would make it inconsistent with `finalize`, so the right fix is a
**unified pass** over all blocking local FFmpeg ops. Logged to the backlog below. Non-blocking reviewer notes
also logged: `edit` does not read `EditResult.output_path` (correctness relies on the passed `output=`, which
is fine/robust), and inputs are `.resolve()`d against `ctx.paths.video` without a confinement check (matching
`graphics.render`; inputs are workflow-authored/trusted).

**Media FFmpeg-heartbeat backlog item (tracked follow-up, non-gating):** blocking local FFmpeg operations —
`media.edit.trim`/`cut` AND `sfvf.finalize` — should emit periodic heartbeats (and/or honor a render-family
`[[limits]]` cap) so the §2.8 silence watchdog cannot kill a legitimately long encode/concat. Do it as one
consistent pass over both (thread the blocking call + beat `ctx.heartbeat`), not a one-off in `edit`.

## 2026-09-02 — B-1b: `media.graphics.render` renders real composed video (HyperFrames)

`media.graphics.render(html, *, duration_s)` now renders the composition for real through the pinned
HyperFrames toolchain (B-1a), replacing the A-5 colour-bar stub. It wraps the workflow's HTML into a minimal
HyperFrames project — `hyperframes.json` + an `index.html` with `<div id="root" data-duration data-width
data-height>` and the `window.__timelines["main"]` readiness signal — and runs `hyperframes render` to a
1080×1920 MP4, returned as a video-relative path string. Per SDK §10 the renderer is free/local, so it runs
**REAL in both dry and non-dry modes** (the A-5 `NotImplementedError` outside dry-run is gone) — this is what
makes real composed video appear at zero cost with no live keys. The toolchain entry is resolved via
`SFVF_HYPERFRAMES_ENTRY` (env) else repo-relative from the SDK's own location (editable install →
`tools/hyperframes/`). Deterministic in `(html, duration_s)`; the filename hash is unchanged from A-5. The renderer copies the
video's `artifacts/` into the temporary project so a composition's video-relative asset references (e.g. the
safe-zone CSS it `@import`s) actually resolve during the headless render — HyperFrames serves the project
over HTTP, so a `file://` base cannot reach them. The readiness signal is registered with `||` so it never
clobbers a timeline the composition registers itself. The render streams the child's output and **emits
heartbeats** so the supervisor's silence watchdog (§2.8) never kills a legitimately slow render (as the
polling media adapters do, §6.3); its safety timeout is a large, env-configurable cap rather than one that
fights the silence limit or the manifest render limit. On a timeout it kills the **whole process tree**
(mirroring `kill_tree` — `taskkill /F /T` on Windows), so HyperFrames' Chrome/FFmpeg descendants aren't
orphaned.

**Recorded review calls (cross-family reviewer, split resolved by the supervisor):** (1) the observation
that `render`'s filename hash keys only on `(html, duration_s)` is **not a cache defect** — that hash is the
output *filename* for dedup, not the step cache key; caching is `ctx.step` on the workflow's inputs, and
SFVF assets are content-addressed (a content change changes the asset's path, hence the html, hence the
key), so stale hits don't arise under the convention. (2) GSAP is loaded from the jsDelivr CDN (matching
HyperFrames' own template), so a render needs network egress; this works in every environment we run (CI +
local) but is a **deferred hardening item** — serve/vendor GSAP locally so offline renders don't stall.
`captions`/`safe_zone_css`/`check` are unchanged (still SFVF/stub; `check`→HyperFrames lands in B-1c). The
render tests moved to `tests/integration/test_graphics_render.py` (skipped where the toolchain isn't
installed; a sampled frame proves the supplied HTML actually rendered).

**Later hardening rounds (process-teardown family) and the exit rule.** After the render core was
pixel-verified and agreed by both reviewer families, the cross-family gate kept surfacing edges in one
territory — process-kill / timeout / reader-thread teardown of a Node→Chrome→FFmpeg tree on Windows. Landed
in this increment: streaming heartbeats; a large env-configurable safety timeout; whole-tree kill via
`taskkill /F /T` mirroring `app/core/proc.py::kill_tree`; `SFVF_HYPERFRAMES_TIMEOUT_S` validated with
`math.isfinite` (nan/inf/non-positive → default) so a malformed value can't disable the deadline; a final
`proc.kill()` fallback when the post-kill `wait` times out; and a **deadline-bounded reader join** — because
Node exiting is not stdout EOF while a descendant still holds the pipe, the reader is joined in
heartbeat-sized slices up to the same safety deadline and, if still alive, the tree is killed and stdout
closed to unblock it, converting a would-be hang into the normal `command failed` path.

**Supervisor exit-rule decision (recorded).** The convergence read for B-1b was reset from round-count to
defect *class*. The render — what the video actually is — has been correct and agreed for rounds; what keeps
churning is the safety-net on a genuinely hard subsystem that will yield edges indefinitely under adversarial
review (the long tail of a hard corner, exactly the endlessly-thorough-verifier case the re-delegation
ceiling exists to stop). Rule from here: a finding **blocks the merge only if it is a new class of defect** —
render correctness, asset resolution, output validity, determinism, anything about what the rendered video
actually is. A further edge in the **process-teardown / timeout / kill-path / threading family does not spin a
new round**; it is logged to the *HyperFrames renderer hardening* backlog below and the increment merges.
Applying that rule to the final review: a render-class finding was raised (that `#root` carries only
`data-width`/`data-height` and no CSS size, so percentage-height content would collapse) and **investigated
empirically before deciding** — a `width:100%;height:100%` child relative to `#root` renders full-bleed
(centre pixel red), proving HyperFrames sizes the root stage from those data attributes at runtime, so the
finding does not hold; it did not block. The concurrent teardown-family finding was logged to the backlog.

**HyperFrames renderer hardening backlog** (tracked follow-up; none block B-1b): (1) **GSAP from CDN** —
`render` reaches jsDelivr at render time (matching HyperFrames' own template); works in every environment we
run, but it is a live external call inside the zero-cost *local* renderer, so vendor/serve GSAP locally so
offline renders don't stall. (2) **`ctx.map` shared-artifacts copy race** (Review A, non-blocking) — the
per-render `copytree` of `ctx.paths.artifacts` into the temp project is not concurrency-safe if renders under
one video ever run in parallel via `ctx.map`; make the artifact staging isolation-safe before that path is
used. (3) **Process-teardown family** — any future kill-path / timeout / reader-thread edge on the
Node→Chrome→FFmpeg tree lands here rather than re-delegating. Concrete open items from the final review:
`_kill_process` early-returns when Node has already exited (`proc.poll() is not None`), so in the
reader-hang path it no-ops on still-alive Chrome/FFmpeg descendants — the reader still unblocks (`_run` closes
the read end of the pipe), but the orphaned descendants are not reaped; and on POSIX `_kill_process` kills
only Node, not the process group. Harden `_kill_process` to reap the descendant tree even when Node is already
dead, and to use a process-group kill on POSIX. Also (Review A note) the kill-and-raise branch's
`"".join(chunks)` can read the list while a still-alive reader appends — GIL-safe, at worst a slightly
truncated error message. (4) **Cold-start render flake** — an occasional
first-render frame can sample non-red (Chrome cold-start / paint timing) while re-runs and the full suite are
green; add a warm-up or CI retry for the render integration test so the gate isn't intermittently flaky.

## 2026-09-02 — B-1a: HyperFrames render toolchain (Stage B begins)

Stage B (the provider layer) starts with the local, zero-cost renderers. This lands the pinned HeyGen
**HyperFrames** toolchain (`heygen-com/hyperframes`, npm `hyperframes` at an exact version under
`tools/hyperframes/`) that the `media.graphics` adapter will render real HTML→video with. CI on
windows-latest installs Node + the toolchain + its headless-Chrome browser and runs a lightweight smoke
render (a 1s 1080×1920 composition → a valid MP4) to prove the least-CI-testable surface works; on machines
without the toolchain installed the render test skips, keeping the suite green. Sourcing is Option A — the
published package, pinned via `package-lock.json`; nothing is cloned or vendored. No auth is used (HeyGen
cloud/auth is not touched; local rendering is free). This is infrastructure only; the adapter wires onto it
next (B-1b).

## 2026-09-02 — Docs: SDK spec aligned to the JSON-native return-type shipping decision

`docs/SFVF_Workflow_SDK.md` (author-facing, no code) brought in line with what Stage A actually shipped
(A-3/A-4/A-5). §5.5 is rewritten as the governing statement of what a workflow gets back: a **file comes
back as a video-relative path string** (not an open `Path`), and a **structured result (`Source`, `Speech`,
…) comes back as a JSON dict read by subscript** (`speech["duration"]`, not `speech.duration`) — because
both must survive the JSON step cache. The one exception is the `Result` `run()` returns: it is
*constructed* (`Result(video=…)`) and handed to the chassis directly, not cached, so `Result.video` is a
real `Path`. The `-> Path` annotations in §6 are noted as shorthand for "a video-relative path string per
§5.5". §6.1 notes each `Source` is a subscript dict; §6.4 rewrites `Speech` as a dict
(`speech["audio"]`/`["timings"]`/`["duration"]`); the §11.1 worked example now uses subscript (its
`Result(...)` construction left as-is). The unbuilt Stage-B media functions' `-> Path` signatures are left
alone (their exact shape settles when built), and the `finalize`→`Result` string/`Path` seam remains a
tracked SDK follow-up.

## 2026-09-02 — A-7: the example workflow — Stage A complete

`workflows/explainer/` is the first real workflow: a composition explainer that exercises the whole
provided-functions surface — `agents.research` + `agents.llm`, `media.speech.speak`,
`media.graphics.render`/`captions`/`safe_zone_css`, and the mandatory `finalize` — each expensive call
wrapped in a cached `ctx.step`. Driven through the real supervisor (subprocess-per-video, the SDK runner,
the step cache) in dry-run, it produces a valid house-format `final.mp4` (1080×1920) at **zero cost**, and
a second run against the same cache reuses every step. It is **gate-free** (`ctx.gate` is deferred to Stage
F) so it runs unattended end to end.

This is the earliest end-to-end observable output — the integration proof that the SDK boundary and the
execution engine work together against a real workflow. **Stage A (the provided-functions dry-run stub
layer) is complete.**

**Known DX seam (recorded):** `finalize` returns a video-relative *string* (uniform with the other media
functions, which must return strings to cache through `ctx.step`), whereas `Result.video` is a `Path`
(§3.3). The example bridges with `Result(video=ctx.video_dir / final)`. A workflow following §11.1's
`Result(video=final)` verbatim would pass a string into a `Path` field. Smoothing this — e.g. having the
runner's result serialisation accept a string, so both forms work — is a small SDK-ergonomics follow-up,
noted so it is not rediscovered as a surprise.

## 2026-09-02 — A-6: `sfvf.finalize` — the mandatory last step

`finalize(video, audio=None, captions=None)` (SDK §6.9) is the required final call of every workflow. It
applies the house format with FFmpeg — H.264, the default vertical 1080×1920 @ 30fps (square pixels,
`setsar=1`, so an anamorphic input still displays a true 9:16), `-14` LUFS loudness —
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
