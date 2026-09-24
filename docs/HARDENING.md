# Hardening ledger — known open technical debt

This is the single ledger of **known, open technical debt**: deliberate deferrals, non-blocking review
findings, and observed flakes that were logged rather than fixed on the spot. It exists so nothing that was
waved past a merge is silently lost.

It is **distinct from `CHANGES.md`**. `CHANGES.md` is the behaviour-change / revert log — what each increment
*did*. This file is what each increment *left open*. An item is added when a merge defers it; an item is
removed (or struck through with the resolving PR noted) when it is actually fixed. Like `CHANGES.md`, updates
ride the increment PR branch to origin.

Each line: **`ID` — description — _source_ — status.** Severity is low unless stated; none of these block the
increments that logged them.

## Struck (reconciled 2026-09-23)

A completeness pass reclassified the ledger by one test: an item earns its place only if the scenario it
describes can actually occur under the deployment target (Windows, single-process, trusted-workflow) and
intended use. Items that provably cannot occur, or are explicitly "not a defect," are struck — an
unreachable item on a debt ledger is noise. Items tied to a provider that is no longer used are struck as
not-applicable.

- **H9 — STRUCK.** The ledger's own text: "correct as-is; a refinement, not a defect." Not debt.
- **H19(c) — STRUCK.** POSIX `fcntl.flock` two-instance-in-one-process semantics: cannot occur on the
  Windows deployment target. Re-open only if a Linux deployment is added (H19(a)/(b) remain open).
- **H35 — STRUCK.** The run-files symlink walk requires an attacker-planted symlink *inside* a run dir,
  which is "unreachable via the API" (run dirs are written only by the trusted child; unprivileged Windows
  blocks symlink creation, WinError 1314). Defense-in-depth against an assumption change, not occurring debt.
- **H50(a) — STRUCK (verify).** Claims a 400/402/5xx reflecting the `Authorization` *header* leaks the key,
  but `_http.request()` now runs `_redact(response.text, auth_headers, …)` on the non-2xx branch, which
  scrubs auth-header values (full value + post-scheme token). Appears already closed; struck pending a
  one-line confirmation. (H50(b), 407 proxy-auth, is a distinct low item — left as-is.)
- **Higgsfield provider dropped — H13, H14, H15, H20(a), H20(b), H25 STRUCK (not applicable).** SFVF no
  longer uses Higgsfield for video generation (other video providers — byteplus/minimax/veo — remain).
  All Higgsfield-specific debt (per-model request fields, 429/malformed-body robustness, unbuilt
  frame/ref generation, estimate-cap-only budget, mid-flight kill-switch, body-field drift) is moot. The
  now-dead Higgsfield adapter itself is queued for removal as a cleanup increment. (H20(c), the OpenRouter
  reconcile-recheck sub-item, remains open.)

## Open

- **H63 — FFmpeg ops have no hard timeout; heartbeats now mask a true hang.** With H6, `finalize`'s
  encode and `media.edit.trim`/`cut` emit periodic heartbeats while FFmpeg runs, so the §2.8 300 s
  silence watchdog no longer kills them. That was the point (legitimately long encodes survive), but
  `_ffmpeg._run` (`subprocess.run`) has no `timeout=`, so a *genuinely hung/deadlocked* FFmpeg op now
  runs forever with no backstop (it emits no `cost` events, so the budget guard never fires either).
  Accepted for H6 (local, non-paid, non-network op on a single-user app — a resource concern, not an
  exploit), but the watchdog backstop is gone for these ops. Fix: give the FFmpeg subprocess a bounded
  `timeout=` in `_ffmpeg._run` (and/or honor a render-family `[[limits]]` cap) so a true hang is still
  detected while legitimate long encodes survive. _Source: H6 security-auditor advisory (PR #155)._ Open.
- **H2 — `ctx.map` shared-artifacts copy race.** Each render `copytree`s `ctx.paths.artifacts` into its temp
  project; this is not concurrency-safe if renders under one video ever run in parallel via `ctx.map`. Make
  the artifact staging isolation-safe before any parallel-render path uses it. _Source: B-1b review A,
  non-blocking (PR #25)._ Open.
- **H3 — `_kill_process` does not reap descendants when Node has already exited.** It early-returns on
  `proc.poll() is not None`, so in the reader-hang path it no-ops on still-alive Chrome/FFmpeg descendants
  (the reader unblocks via stdout close, but the descendants leak); on POSIX it also kills only Node, not the
  process group. Reap the tree even when Node is dead; use a process-group kill on POSIX. _Source: B-1b review
  B (PR #25)._ Open.
- **H4 — reader-thread teardown read/write race.** In the kill-and-raise branch, `"".join(chunks)` can read
  the list while a still-alive reader thread appends — GIL-safe, at worst a slightly truncated error message.
  _Source: B-1b review A, non-blocking (PR #25)._ Open (low).
- **H5 — cold-start render flake.** The first render can occasionally sample a non-red frame (Chrome
  cold-start / paint timing) while re-runs and the full suite are green. Add a warm-up or a CI retry for the
  render integration test. _Source: B-1b (PR #25)._ Open.
- **H7 — CI flake: `test_list_returns_runs_newest_first`.** On windows-latest this app-layer test failed once
  with a stub run reaching terminal `failed` (not a timeout), then passed on a clean re-run; in the same
  failing run the sibling test using the identical `succeeds` stub passed. A pre-existing subprocess /
  concurrency transient under CI load, not tied to any provider code (B-2 lazy-imports kinocut; the run path
  never loads it; passes 4/4 locally). If it recurs, harden the two-run ordering test's launch/settle — or the
  run-admission / subprocess-spawn path — against the race. _Source: observed on B-2 CI (PR #26); previously
  recorded only in local `PROJECT_STATUS.md`, never shipped to origin until this ledger._ **RECURRED on B-4b CI
  (PR #29): the same test hit a Windows `PermissionError` on `request.json`, AND `test_supervisor.py::
  test_heartbeating_stub_survives_past_silence_limit` flaked the same way (stub run → terminal `failed`); both
  passed on re-run.** So this is now a recurring, CI-blocking flake class across the app-layer subprocess-run
  tests (`test_runs.py`, `test_supervisor.py`, `test_run_events.py`) under windows-latest load — not a
  one-off (blocked B-4d's CI twice more before greening on the 3rd re-run). **CORE RACE FIXED (PR #32):** the
  cause is a Windows file-sharing violation between `write_json_atomic`'s atomic `os.replace` and a concurrent
  `read_json` `read_text` of the same `request.json`/`video.json`; both now retry on transient
  `PermissionError` (`app/core/records.py`), which removes this flake class. **Residual vectors (open, low):**
  (a) test-teardown `shutil.rmtree` of a run dir a subprocess handle still holds can raise its own
  `PermissionError` — a separate path not covered here; (b) `events.jsonl` (`append_event`/`read_events`) is
  not wrapped by the record retry — `append` is `O_APPEND` and `read_events` tolerates torn lines, but the same
  class could surface there. Reopen/extend if either residual vector produces a flake. Open (low, residual).

- **H8 — `RateLimiter.configure` replaces a live semaphore.** `configure(provider, …)` rebuilds the
  provider's `threading.Semaphore`, so reconfiguring **while slots are active** leaves old holders on the old
  semaphore while new calls acquire the new one — the concurrency cap can be briefly bypassed. Not hit in
  intended use (each provider is configured **once at adapter startup, before its first request**); the
  contract is configure-before-use. Enforce that (reject/ignore reconfiguration once a provider is in use) or
  adjust the live semaphore's capacity in place instead of replacing it. _Source: B-4b review B, P2 (PR #29)._
  Open (low).
- **H9 — `RateLimiter.slot` sleeps while holding the per-provider lock.** The paced/back-off `sleep` runs
  under `state.lock`, so a concurrent `penalize()` (recording a `Retry-After`) blocks until the in-flight sleep
  finishes — the deadline it then records is still correct, just a beat late. Refinement: compute the wait
  under the lock, then release it before sleeping. Correct for every intended paced/concurrent/back-off
  combination as-is (per review A analysis); this is a refinement, not a defect. _Source: B-4b review A, note
  (PR #29)._ Open (low). **STRUCK 2026-09-23 — see Struck section.**

- **H12 — OpenRouter web-search mechanism may be dated by the time research goes live.** `agents.research`
  uses the `plugins:[{"id":"web"}]` form (verified current when built); OpenRouter appears to be moving to an
  `openrouter:web_search` mechanism. No live call is made in dry_run/mocked builds, so this doesn't affect
  correctness now — but **re-verify the web-search request shape against current OpenRouter docs before the
  first live `research` call**, and update the pinned `_RESEARCH_MODEL` / plugin form if needed. _Source: B-4d
  review B, non-blocking currency note (PR #31)._ Open (low).

- **H13 — Higgsfield per-model request fields are best-effort until verified live.** `media.video.generate`
  sends `{prompt, duration: duration_s, **extra}`; Higgsfield's request body is model-dependent and the exact
  per-model field names (e.g. is it `duration`/`seconds`/`duration_ms`? aspect ratio? resolution for the credit
  estimate?) were not pinned per-model from the OpenAPI. Before the first LIVE Higgsfield call, verify the
  chosen model's request schema (per-model OpenAPI) and fix the `duration_s`/aspect/resolution mappings; `extra`
  is the escape hatch meanwhile. _Source: B-5, dry_run/mocked (PR #33)._ Open (verify-before-live). **STRUCK 2026-09-23 — see Struck section.**
- **H14 — Higgsfield response robustness (429 retry + malformed 2xx body).** Non-2xx on submit, poll, AND
  download are now handled (each raises a labeled `RuntimeError`; a failed download never saves an error body
  as the video — B-5 review B P1/P2, fixed). Still open: (a) no `Retry-After`/429 backoff-retry (it queues
  behind the §5.5 limiter but doesn't `penalize`+retry like `agents._post_chat_completion`); (b) a well-formed
  2xx with an unexpected body shape (missing `request_id`/`status`/`video.url`) raises a bare `KeyError` rather
  than a clear adapter error. Add the 429-retry and defensive body parsing before any unattended live use.
  _Source: B-5 review A + B (PR #33)._ Open (low, pre-live). **STRUCK 2026-09-23 — see Struck section.**
- **H15 — Higgsfield frame/ref-conditioned generation not built.** `first_frame`/`last_frame`/`refs` raise
  `NotImplementedError`; image-to-video and first-last-frame endpoints (plus the image-upload mechanics and the
  `media.analyze.frame` clip-chaining path, §6.3/§6.3a) are a follow-up increment. _Source: B-5 (PR #33)._ Open. **STRUCK 2026-09-23 — see Struck section.**
- **H16 — secret-store durability (non-blocking, residual).** RESOLVED in S1: the KDF was strengthened to
  scrypt `n=2**17` and the on-disk format now carries a 1-byte version header (`_KDF_BY_VERSION`), so future
  param bumps are migratable; empty passphrases are rejected. Residual (low): the parent directory is not
  fsync'd after `os.replace` (the store can't be *truncated* — atomic replace — but the rename may not survive
  an immediate power loss). The `chmod 0o600` note was invalid (mkstemp creates owner-only files on POSIX and
  `os.replace` preserves the mode). _Source: S1 review A/B (PR #34)._ Open (low, residual).
- **H17 — passphrase must not leak to subprocesses.** RESOLVED in S2a: a shared `app.core.secrets.subprocess_env()`
  (os.environ minus `SFVF_SECRETS_PASSPHRASE`) is applied to every real spawn — the workflow runner
  (`_start_runner`) AND the env-setup / `pip install` / interpreter-probe spawns in `env.py` (`_run_timed`,
  `default_find_python`), closing the HIGH finding that workflow-declared dependency builds could read the
  master passphrase. Residual (low, defense-in-depth): `app/core/proc.py::kill_tree` runs `taskkill` with the
  full inherited env — NOT a real vector (taskkill is a fixed trusted OS binary executing no workflow code),
  but routing it through `subprocess_env()` too would make "no spawn inherits the passphrase" universal.
  _Source: S1 review B (fixed S2a); S2a review A note (PR #35)._ Open (low, residual).
- **H19 — budget-breaker model residuals (T2a).** The T2a `BudgetGuard` (`sfvf._budget`) is a hard
  pre-call gate; these are limits inherent to its minimal reserve-then-reconcile / calendar-day model,
  to close as the engine grows (T2b wiring + Stage C metering):
  (a) **Midnight-in-flight (low/med):** `day_total` attributes a reservation to the UTC calendar day of
  its `reserved` ts. A reservation opened at 23:59Z is invisible to the next day's total at 00:01Z, so a
  fresh day's ceiling can be reserved while that call is still in flight — a bounded, one-ceiling
  overshoot across a midnight boundary. (b) **Underestimate slips one call (inherent):** `reserve` is the
  only gate; a single underestimated call whose reconciled `actual` exceeds the ceiling is allowed after
  the fact (subsequent reserves are then correctly denied because the actual counts). Mitigated later by
  Stage-C forecasts and per-provider estimators. (c) **POSIX same-process lock (low):** the cross-process
  lock is validated on Windows (the deployment target); on POSIX, `fcntl.flock` semantics across two
  `BudgetGuard` instances in one process are not exercised — revisit if CI or deployment adds Linux.
  **T2b acceptance requirements (caller contract, not engine defects):** (i) treat **ANY** exception
  raised by `reserve` as a hard **denial** (fail-closed → refuse the paid call / `stopped-budget`), not
  only `BudgetExceededError`/`KillSwitchEngagedError` — a lock-acquire `OSError`/timeout (Windows
  `LK_LOCK` blocks ~10s then raises), a `ValueError` from a poisoned amount, or an `OverflowError` from an
  absurd estimate must all stop the call. (ii) Never pass `estimate=0` as an "unknown/placeholder" cost —
  a zero estimate reserves nothing and never accumulates, so use a conservative positive floor before a
  live call. (iii) Call `reconcile` exactly once per token (the engine is last-write-wins and cannot tell
  a rewrite from a refund). Also noted (engine, low): a complete-but-valid ledger line with a malformed
  `ts` is excluded from `day_total` (still counted in `run_total`) — cannot arise from engine-written
  entries; and a `per_day`/`per_run` ceiling set to `inf` refuses everything (the "unlimited" convention
  is meter **absence**, not `inf`). _Source: T2a review A/B (PR #38)._ Open.
- **H20 — budget-gate wiring residuals (T2b-1).** The SDK now gates both paid providers before spending
  (`Context._budget_reserve`/`_reconcile`), but two limits remain until Stage C / T2b-2:
  (a) **Higgsfield is estimate-capped only** — `generate` reserves the configured estimate but never
  reconciles a real amount (the submit returns no per-request cost), so its per-run/per-day cap is only
  as tight as the configured estimate. Set the Higgsfield estimate ≥ a realistic per-video credit cost,
  and add a real reconcile (from the status/credits response) in Stage C. (b) **Kill-switch is checked at
  reserve time, not mid-flight** — engaging the switch after a Higgsfield reserve does not abort the
  in-flight submit/poll/download (up to the poll timeout). (c) OpenRouter reconcile does not re-check
  ceilings (H19(b) applies): one allowed call whose real `usage.cost` exceeds headroom breaches after the
  fact; the next reserve is then denied. Also: production spend stays **ungated until T2b-2** populates
  `ContextFile.budget` on real runs. _Source: T2b-1 review A/B (PR #39)._ Open.
- **H21 — a real paid run with no budget config is not refused (fail-open-when-unset).** T2b-2a makes the
  gate live *when* `SFVF_BUDGET_CONFIG` is set, but a non-dry_run run of a paid-provider workflow with the
  env **unset** still runs ungated: T2b-1 deliberately made "no budget config → passthrough" so the
  pre-budget OpenRouter/Higgsfield mocked-integration tests and the secret-injection/redaction security
  tests (which run the real path / declare `requires_keys` with no budget) keep passing. Closing this
  (refuse a real paid call when no budget is configured — at the SDK reserve site or at admission) requires
  reversing that passthrough contract and migrating those merged tests to supply a budget, so it is a
  deliberate follow-up, not folded in here. **Mitigation for the attended first run:** the attended
  protocol stops before the first paid call and positively verifies the gate is live (app budget loaded /
  `context.json` carries the budget block), so the fail-open cannot silently apply to the attended run;
  the exposure is future **unattended** runs. Fix later: flip `_budget_reserve` to raise when a paid call
  is attempted with no config (or refuse at admission on `requires_keys` + no budget), and migrate the
  affected integration/security tests to provide a budget. _Source: T2b-2a design review._
  **RESOLVED (H21 increment):** `Context._budget_reserve` now raises `BudgetError` when no budget is
  configured, refusing the paid call before any HTTP. Enforcement is at the SDK reserve site — reached
  only on the non-dry paid path, after the key read — so the blast radius was just the passthrough
  contract (reversed) + the three real-adapter integration tests (migrated to carry a permissive budget);
  the secret-injection/redaction suites were untouched (their stubs never reserve), avoiding the feared
  security-suite migration. A `BudgetError` here is mapped to `stopped-budget` by T2b-2c, so an
  unconfigured real run stops cleanly with no spend. See Resolved.
- **H24 — budget-denial signal is the runner exit code alone.** The supervisor maps child exit code
  `EXIT_BUDGET_DENIED=2` to `stopped-budget`. A workflow that itself terminates with code 2 (e.g.
  `sys.exit(2)`, or an argparse error — `SystemExit` bypasses the runner's `except Exception`) would be
  mislabeled `stopped-budget`. Consequence is a status **label** only — no spend-authorization effect (the
  SDK gate already refused before any HTTP) — and idiomatic workflows return a `Result`, so the trigger is
  non-idiomatic. Harden by requiring BOTH exit code 2 AND a recorded `reason:"budget"` error event before
  mapping (the runner already emits both together). Flagged by all three T2b-2c reviewers as non-blocking.
  _Source: T2b-2c review (diff-reviewer NOTED / security-auditor ADVISORY / review B Medium)._ Open.
- **H25 — Higgsfield adapter body fields drifted from the real API (residuals).** Verified against
  the live OpenAPI spec (2026-09). Two model-body drifts remain (the poll-auth bug found alongside
  them was FIXED in the smoke_higgsfield increment — see Resolved):
  (a) **duration is a float, not the int enum.** `media.video.generate` maps `duration_s` into the
  body as a float (`5.0`), but the `duration` field is an integer enum (`5`/`10`) — a non-5/10 or
  float value risks a 422. `smoke_higgsfield` sidesteps it by omitting `duration_s` (the API then uses
  its int default `5`).
  (b) **aspect_ratio is model-dependent.** `kling-video/v2.1/master` accepts `aspect_ratio`
  (`1:1`/`16:9`/`9:16`, default `1:1`), but `kling-video/v2.5-turbo/pro` (the smoke's cheap model) does
  NOT expose it at all — its body is only `{prompt, duration, cfg_scale, negative_prompt}`. So a
  guaranteed-vertical short-form needs v2.1 master (or another model that exposes `aspect_ratio`); the
  smoke runs v2.5-turbo/pro at the model's default ratio (cosmetic for a loop-validation smoke).
  Fix when a real short-form workflow needs these via typed params: coerce `duration` to the int enum,
  surface `aspect_ratio` as a first-class `generate(...)` arg, and pick a model that supports it. The
  frozen contract `test_video_higgsfield.py::test_generate_real_passes_extra_and_duration` (asserts
  `duration == 8.0`) is reversed as part of that fix. Confirmed CORRECT: base URL, `Key id:secret`
  auth on submit AND poll, submit→poll→download, success status `completed`, `video.url` result path,
  `{failed,nsfw,canceled}` terminal set. _Source: Higgsfield API verification (step-4 prep)._ Open. **STRUCK 2026-09-23 — see Struck section.**
- **H26 — forecast latest-per-meter is not strictly event-ordered across concurrent videos (C-2).**
  `record_event` (append) and `record_forecast` (accumulator + request.json write) take the run lock
  separately, so if two videos in one request forecast the SAME meter concurrently, the durable
  `request.forecast[meter]` may reflect the earlier-appended event rather than the last one. Accepted
  as low-impact: forecasts are soft, non-blocking, informational reservations; the consumer (C-3
  atomic pre-flight) applies to atomic single-episode workflows where there is no intra-request
  concurrency; and "latest across independent concurrent video threads" is itself ill-defined. A
  strict fix would fold the forecast accumulator update into `record_event` under one lock hold; do
  that only if a real multi-video-same-meter forecasting workflow appears. _Source: C-2 review B._
  **RESOLVED 2026-09-24 (Stage-C) — see Resolved: H26.**
- **H29 — the paid/cheap cache layout orphans pre-existing single-partition entries (C-6).** C-6
  moved cache storage from `<root>/{entries,blobs}` to `<root>/{paid,cheap}/{entries,blobs}`. Any
  cache written before C-6 is now unreachable (a one-time miss — recomputed on next use) and its
  files sit under the old paths, which `evict_cheap` never scans, so they leak disk forever. Accepted
  for now: the cache is DERIVED and safe to lose (§5.9), and negligible cache has accumulated in this
  project; a mature deployment with real paid cache would want a one-time migration (or a legacy-path
  fallback + cleanup) so pre-C-6 paid work is not silently re-purchased. Fix when a migration path is
  warranted. _Source: C-6 review B (P1, de-scoped as derived-data-safe)._ Open.
- **H30 — cheap-cache eviction is per cache root and its initial total counts orphan blobs (C-6).**
  Two low-impact refinements to `evict_cheap`: (a) it bounds each `<workflow>/<mode>` cache root
  independently, not a single global ceiling across all partitions (§8.7 wants one global size) — so
  N workflows can hold up to N×ceiling; a global sweep can reuse the same size logic later. (b) The
  initial over-ceiling check counts every blob present including orphans, while the per-eviction
  recompute counts only referenced blobs, so a partition over-ceiling purely from an orphan blob (a
  crash between blob-copy and entry-write) evicts one avoidable LRU entry before the orphan is
  reclaimed at pass end — the partition still ends correctly sized. Also noted: the eviction loop is
  O(n²) in entry count (fine for local caches). _Source: C-6 review (diff-reviewer + security-auditor
  NOTES)._ Open.
- **H31 — library store: unlocked alias RMW + hash-then-copy TOCTOU (D-1).** Two content-integrity
  edges in `sdk/sfvf/library.py`, both accepted for v1: (a) `aliases.json` is a read-modify-write
  with an atomic replace, so two workflows sharing a namespace and writing aliases at the same instant
  can lose one update (torn JSON is prevented, lost updates are not). Architecture §5.10 explicitly
  accepts **no locking in v1** (it names `catalog.json` as the contended object and says the fix, if
  it ever bites, is a lock around rebuild, not a database); aliases are mutable handles and the id is
  always recoverable, so impact is low. (b) `put` hashes the source, then copies it — if the caller
  mutated its own just-written file between the two reads, the stored blob would not match its sha256
  name. The identical hash-then-copy pattern lives in `sdk/sfvf/cache.py` and was accepted there;
  realistic exposure is a caller bug. Fix both together if warranted: a lock (or last-writer-wins log)
  around alias writes, and a copy-to-temp→digest-temp→rename fs util (promote the shared
  `_copy_atomic`/`_file_digest`/`_write_json_atomic` out of `cache.py` into a non-underscore module at
  the same time). _Source: D-1 review B (P1a + P1c, de-scoped as v1-accepted per §5.10)._ Open.
- **H32 — self-review slideshow hard-gating + partial-black calibration deferred (E-1).** §5.8's
  slideshow threshold "cannot be one number" and must follow the declared `[output]` format, which is
  not yet in the runtime Context (house format is fixed, per A-6). So E-1 RECORDS the slideshow
  verdict + `motion_score` but does NOT hard-fail on it — a single house-default threshold, made worse
  by measuring `scdet` on the letterbox-padded finalize output, would false-fail legitimate low-motion
  renders (talking-head/product/clean AI: measured 0.0006 padded vs 0.0235 native) and discard a paid
  video, which is worse than missing a slideshow. Likewise black hard-fails only on a MAJORITY-black
  output (unambiguously broken); finer partial-black gating (an absolute contiguous-black bound) is
  deferred with the same calibration. When `[output]` reaches the Context, add per-format thresholds,
  measure slideshow on the content region (crop the pad) or the pre-house-format source, and turn the
  slideshow verdict into a hard failure. Broken-frame corruption beyond black is not detected (ffmpeg
  conceals decode errors); blackdetect + ffprobe validity is E-1's coverage. Also NOTED: the clipping
  check is largely inert on the real finalize path because `loudnorm` true-peak-limits before the
  measurement (it still works when `content_review` is called directly). _Source: E-1 review
  (Sol P1×2 + diff-reviewer SHOULD-FIX/NOTES)._ Open.
- **H33 — composition self-review (§6.5) v1 calibration + `[output]` plumbing (E-2a/E-2b).**
  `media.graphics.check()` gates outside-viewport / safe-zone / text-clipped / missing-font, and
  `finalize` auto-runs it on every composition rendered in a run. Deferred/limited in v1:
  (1) **safe-zone follows `[output]`** — `safe_zone` is `"tiktok" | "none"` per the declared
  `[output]`, which is not yet in the runtime Context, so `finalize` uses the fixed house default
  (tiktok → `safe_zone=True`); when `[output]` is plumbed, pass the workflow's declared `safe_zone`
  instead of the hardcoded default (a `safe_zone="none"` workflow must not be margin-gated).
  (2) **missing-font is environment-sensitive** — it flags a text element whose primary family is a
  loaded-`@font-face` family that errored; a remote font (e.g. the explainer's Google-Fonts
  `@import`) that fails to load in a headless environment without network would flag as missing even
  though the render falls back to a legible system font. Consider self-hosting/embedding brand fonts,
  or downgrading missing-font to a recorded signal, when this bites. Also the E-2a-noted global
  family match: an unused weight/style that 404s flags every element using that family.
  (3) **discarded-candidate renders are still checked** — `finalize` checks every composition
  rendered in the run (via `render-*.html` sidecars), not only the one(s) that fed the final video;
  a violation in a rendered-but-unused composition fails the run. No provenance tracking in v1.
  (4) **`check()` copies the whole `artifacts/` tree per call** (incl. every `render-*.mp4`); O(N ×
  artifact size) for a multi-composition run — fine for the common single-composition case.
  _Source: E-2a review (diff-reviewer NOTES) + E-2b review (diff-reviewer + Sol Review B)._ Open.
- **H34 — self-review record embeds the absolute output path on the fatal probe-error path (E-3).**
  In `finalize._self_review`, the "output missing" / "no video stream" branches put the absolute
  `dest` path into the `self_review` `structural`/`failures` written to `video.json`. Secret *values*
  are redacted, but the host filesystem layout (workspace/home path) is not a secret and passes
  through verbatim. Not a live hole — the record lives inside the run tree — so defence-in-depth:
  emit a run-relative path (e.g. `dest.name`) on those branches so a shared record does not disclose
  absolute host paths. _Source: E-3 security-auditor ADVISORY._ Open.
- **H35 — run files-listing endpoint: symlink-alias / walk hardening (E-4a).** `GET
  .../runs/{run_id}/files` (`list_run_files`) is confinement-sound (every entry's resolved path is
  re-checked against `run_root`; `context.json` and dot-dirs excluded), and every edge below requires
  an attacker-planted symlink *inside* the run dir — unreachable via the API (run dirs are written
  only by the trusted child process; unprivileged Windows blocks symlink creation, WinError 1314).
  Defence-in-depth, tracked: (1) [FIXED in E-4a re-delegation, locked by
  `test_listing_excludes_context_json_symlink_alias`] the `context.json` exclusion now also tests
  `resolved.name`, matching the sibling `get_run_file`, so a symlink alias (`notes.txt ->
  context.json`) is excluded from the listing too. (2) On 3.12 `Path.rglob` follows directory
  symlinks with no cycle
  guard; when the runtime reaches 3.13 pass `recurse_symlinks=False` (or `os.walk(...,
  followlinks=False)`). (3) `list_run_files` gates on `run_dir.is_dir()` while `get_run` requires
  `request.json` — tightening the listing to require `request.json` makes it a true "is this a real
  run" check and aligns the two. (4) the serving endpoint could also reject dotfiles (the listing
  already hides them). _Source: E-4a diff-reviewer + security-auditor ADVISORY/NOTED._ Open. **STRUCK 2026-09-23 — see Struck section.**
- **H36 — scheduler engine uses naive local `datetime`: DST + near-midnight grace edges (F-2).**
  `app/core/scheduler.py` computes a slot's fire window with `now.replace(...)` on `now.date()` (no
  timezone math, per the F-2 brief's "naive local datetime" allowance). Two edges for the follow-on
  runner-wiring increment to account for: (1) on a DST spring-forward/fall-back day the wall-clock
  window can shift by an hour; (2) a near-midnight slot (e.g. `time_of_day="23:58"` with the 5-min
  `DEFAULT_GRACE`) silently loses the post-midnight portion of its grace — after 00:00 the date and
  weekday roll over and `due` recomputes to the far-future same day, so the window is shortened, not
  doubled (confirmed it cannot re-fire). Both are consistent with "missed slots are skipped." When
  the runner + timer land, either widen the window computation across the day boundary or accept the
  clip explicitly. _Source: F-2 diff-reviewer NOTED._ Open.
- **H37 — schedules CRUD write-serialisation is process-local + malformed-file surfaces as 500 (F-3).**
  `app/api/schedules.py` serialises every read-modify-write of `schedules.json` under a module-level
  `threading.Lock`, which holds only within one process — correct for the current single-process
  uvicorn model, but two workers on separate processes could still lose an update (last atomic
  `os.replace` wins). If the app is ever served multi-worker, close it with a cross-process file lock.
  Separately, a corrupt on-disk `schedules.json` makes `read_schedules` raise `ScheduleError`, which
  surfaces as an unhandled 500 on `GET /api/schedules` (an availability nit, not a security hole, and
  the file is only ever written atomically by this same API); a follow-on may map it to a clear 422.
  _Source: F-3 security-auditor ADVISORY._ Open.
- **H38 — Schedule tab UI polish: day-pill a11y, blocker icon, raw-rgb token (F-4).** Three
  non-blocking advisories from the F-4 review of `frontend/src/components/ScheduleView.tsx` +
  `frontend/src/index.css` (same advisory classes deferred at E-4b): (1) the read-only weekday pill
  strip conveys active days visually only — a screen reader hears "M T W T F S S" with no active-state
  cue (the interactive form toggles are fine, they carry `aria-pressed`); add a per-pill `aria-label`/
  state or a text day summary. (2) The ported `.blocker .ico` rule is dead — the real-spend warning
  renders text with no leading warning icon as the mockup's blocker carries; add the icon element or
  drop the unused rule. (3) `.blocker`'s border is a literal `rgb(209 116 108 / 40%)` (faithful to the
  mockup; no red-at-40% design token exists) — a `--red-border`-style token would single-source it.
  All mirror the approved `v-schedule` mockup and violate no frozen a11y MUST. _Source: F-4
  design-auditor ADVISORY._ Open.
- **H39 — scheduler runner: restart re-fire, un-plumbed `gates_auto`, shutdown join (F-5).** Three
  non-blocking advisories from the F-5 review of `app/core/scheduler_runner.py` + `app/main.py`.
  (1) **Restart re-fire (cost-safety, ELEVATED) — RESOLVED (this PR).** `SchedulerState.fired` was
  in-memory (F-2) and the driver runs `tick_once()` immediately on startup, so an app restart INSIDE a
  slot's 5-min grace window re-fired an already-fired slot — a duplicate real-money run for an
  `allow_real_spend=True` entry. `tick()` now persists fired slot keys to `scheduler_fired.json`
  (pruned to the current day so it cannot grow forever) after each fire, and `SchedulerDriver` seeds
  `SchedulerState` from that file on construction, so slot dedup survives a restart. `read_fired`/
  `write_fired` are best-effort (a filesystem fault is swallowed; the budget ledger still bounds any
  re-fire). Covered by `tests/core/test_scheduler.py::test_restart_within_grace_seeded_from_disk_does_not_refire`
  (+ persist/prune tests) and `tests/core/test_scheduler_runner.py::test_driver_seeds_fired_from_disk_and_does_not_refire`. (2) **`gates_auto` not yet honored.** §5.7 says each entry carries
  the approval-gate auto/pause flag, but the runner has NO gate-bypass parameter yet (`run_request`
  takes none; the only `gate` state today is the silence-monitor heartbeat, unrelated) — so the flag
  cannot be plumbed until the approval-gate RUNTIME lands. The field is captured (F-1) and shown (F-4)
  in anticipation; wire `gates_auto → start → admit_run → run_request` when the gate runtime exists.
  (3) **Shutdown join under lock.** `SchedulerDriver.stop()` holds `_lifecycle_lock` across
  `thread.join()`; if a tick is mid-`admit_run`/`ensure_env` (e.g. a first-time venv build) shutdown
  blocks for that duration — availability at shutdown only; consider a bounded join. _Source: F-5
  security-auditor ADVISORY; (1) resolved by this PR, (2) blocked on the approval-gate runtime
  (Phase 5), (3) Open._ Open (2)/(3).
- **H40 — headless-Chrome/FFmpeg can still orphan (invisibly) on an abnormal node exit (test-infra).**
  The composition-check / render path spawns `node` via `sfvf.media.graphics._run`, which now sets
  `CREATE_NO_WINDOW` on Windows so no console window appears (fixing the visible pile-up of
  `chrome-headless-shell` terminal tabs). Normal and timeout exits are cleaned up (`dom_check.mjs`
  closes the browser/server in a `finally`; `_run`'s `_kill_process` kills the node tree on timeout).
  But a hard crash of the Python/node process could still leave a `chrome-headless-shell` / FFmpeg
  descendant running — now INVISIBLE (no window), so it no longer clutters the terminal but could
  accumulate as background processes over many crashed runs. Low impact (no UI, no spend); a future
  hardening could kill the whole child process tree on `_run` exit (Windows: taskkill /T, or a job
  object). _Source: chrome-console fix follow-up._ Open.
- **H61 — served run files get no value-level secret redaction.** `get_run_file` (`app/api/runs.py`)
  blocks `context.json` by name and now serves a scrubbed/blocked `result.json` (H18); `events.jsonl`
  is redacted at write. **(b) `.steps/**` path-fetch — RESOLVED (this PR):** the dot-prefixed step
  cache was hidden from the *listing* but still fetchable by path (`get_run_file` had no dot-part
  guard); `get_run_file` now refuses any dot-prefixed path part, matching the listing exclusion.
  Covered by `tests/api/test_secret_exposure.py::test_dot_prefixed_run_files_are_not_downloadable`.
  **(a) `shared/artifacts/**` still open:** artifacts are listed and downloadable verbatim with no
  value-level redaction — but artifacts are the workflow's INTENDED downloadable outputs, so blanket
  blocking/redacting them would break legitimate use; a workflow that writes its own injected key into
  an artifact leaks it on download. Pre-existing, narrow trigger (a workflow leaking its own key,
  which it could exfil many other ways). Fix option if ever needed: a best-effort value-redaction pass
  over served artifact files. _Source: H18 security-auditor advisory (PR #152); (b) closed by this PR._
  Open (a, low).
- **H62 — `_run_prepare` success-path re-parse crashes on a pathological `result.json`.** After the
  `finally` scrub, the success path re-reads `result.json` with
  `json.loads(result_path.read_text(encoding="utf-8"))`. A `prepare()` that RETURNS a pathologically
  deep payload (≈2000 nested levels) makes that `json.loads` raise `RecursionError`, and an invalid
  byte would make `read_text` raise `UnicodeDecodeError` — either crashes `_run_prepare` on the
  success path (the failure path returns earlier and is unaffected). Pre-existing and NOT a secret
  leak (the `finally` scrub already redacted the file by then); a robustness gap only, triggered by a
  hostile/buggy prepare return. Fix: bound/relax the re-parse (guard `RecursionError`/decode there,
  or reuse the already-parsed payload). _Source: H18 review A (diff-reviewer NOTED + security-auditor
  advisory, PR #152)._ Open (low).
- **H64 — prepare-phase spend is in Statistics but not yet in cost ESTIMATION.** The prepare phase's
  aggregated cost is now persisted to `request.prepare_cost` and counted in the Statistics tab, but
  `app/core/estimate.py` still estimates purely per-video (`_run_uncached` reads only `video.json`),
  so a prospective run's estimate and the C-3 atomic pre-flight omit the shared prepare cost. For a
  workflow whose prepare spends materially (e.g. web-sourcing behind a paid VLM check), the estimate
  under-states the true run cost by that fixed per-run overhead. The fix is a follow-on because it
  needs a model decision: the per-video `Estimate` must carry a separate per-run overhead term (from
  the last comparable runs' `prepare_cost["uncached"]`) that `scale_estimate` adds ONCE rather than
  multiplying by `video_count`. Deferred to the estimation increment. _Source: prepare-cost Stage-C
  increment (statistics half); chip task_bf07b7fd._ Open.

## Resolved

- **H1 — GSAP loaded from CDN at render time** (resolved by this PR). `_index_html` (used by both
  `render` and `check`) injected `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js">`,
  so the headless browser fetched GSAP over the network on every render/check — a live external call in
  the otherwise zero-cost local renderer that stalled offline renders. The exact pinned `gsap@3.14.2`
  (unmodified, GreenSock standard license) is now vendored at `sdk/sfvf/media/gsap.min.js` and inlined
  into the HTML via a module `_GSAP_JS` constant read at import; the SDK is installed editable so the
  sibling data file is available at runtime (as `dom_check.mjs` already is). Renders/checks make no CDN
  call. Covered by `tests/sdk/test_graphics.py::test_index_html_inlines_gsap_and_makes_no_cdn_call`.
  _Source: B-1b review (PR #25); closed by this PR._
- **H6 — blocking local FFmpeg ops emit no heartbeats** (resolved by this PR). `sfvf.finalize`'s
  house-format encode and `media.edit.trim`/`cut` run FFmpeg synchronously with its output captured,
  so the workflow subprocess produced no stdout during a long encode/concat and the §2.8 300 s
  silence watchdog could kill a legitimately long op. A new `emit.heartbeat_during(name, *,
  waiting_on, interval=30.0)` context manager runs a daemon thread that emits a `heartbeat` event
  every `interval` seconds (well under 300 s) while the wrapped op runs; the first heartbeat is one
  interval in, so a fast op emits none. Applied as one consistent pass over both: `_apply_house_format`
  wraps its encode and `edit.trim`/`cut` wrap their kinocut calls. `emit()` writes to stdout under a
  module lock, so emitting from the helper thread is safe. Covered by `tests/sdk/test_emit.py`,
  `tests/sdk/test_edit.py`, and `tests/sdk/test_finalize.py::test_finalize_wraps_the_ffmpeg_encode_in_a_heartbeat`.
  _Source: B-2 review B (PR #26); closed by this PR._
- **H11 — `agents` trusted the OpenRouter 200 body shape** (resolved by this PR). `agents.llm` read
  `data["choices"][0]["message"]["content"]` and `agents.research` read `data["choices"][0]["message"]`
  + `ann["url_citation"]["url"]`, so a malformed/unexpected 200 (no/empty choices, choice without
  message, message without a string content, or a `url_citation` annotation missing its inner object
  or `url`) raised an opaque `KeyError`/`IndexError`/`AttributeError` (llm) or `KeyError` mid-parse
  (research). A new `_first_message(data)` helper raises a clear `RuntimeError` on a bad body shape;
  `llm` validates `content` is a `str` up front (covering the schema and non-schema paths); `research`
  skips malformed `url_citation` annotations instead of raising. (`usage.cost` was already defensive
  via `_usage_cost`.) Covered by `tests/sdk/test_agents.py::test_llm_raises_a_clear_error_on_a_malformed_body`
  (parametrized), `::test_research_raises_a_clear_error_on_a_malformed_body`,
  `::test_research_skips_malformed_url_citation_annotations`. _Source: B-4c/B-4d review A (PR #30/#31);
  closed by this PR._
- **H27 — cost estimate is now per-video over complete videos, scaled by the count** (resolved by
  this PR; Stage-C). `estimate_cost` summed each run's uncached cost over ALL videos (per-run,
  including non-`complete` videos of a `partial` run) and the atomic pre-flight compared it to the
  budget without scaling by the requested `video_count` — so a multi-video run was under-estimated
  (could be admitted over the per-run ceiling) and non-complete-video cost leaked into the average.
  `_run_uncached` now counts only `video.status == "complete"` videos and returns a PER-VIDEO figure
  (per-meter sum / complete count); a new `scale_estimate(est, count)` multiplies `per_meter` by the
  requested count; the supervisor scales by `video_count` before `check_atomic_budget` (frozen
  signature unchanged). 1-video/all-complete runs are behaviour-neutral (per-run == per-video). Also
  feeds the C-5 Statistics tab (a per-video unit). Covered by `tests/core/test_estimate.py::`
  `test_estimate_is_per_video_average_over_complete_videos`,
  `::test_estimate_excludes_non_complete_videos_from_the_per_video_unit`,
  `::test_scale_estimate_multiplies_per_meter_by_the_count`. _Source: C-4 review B (P1 video_count +
  P2 partial-video cost); closed by this PR._
- **H26 — forecast latest-per-meter is now strictly event-ordered** (resolved by this PR; Stage-C).
  `_RunState.record_event` (append to `events.jsonl`) and `record_forecast` (accumulator +
  `request.json` write) took the run lock separately, so two videos in one request forecasting the
  SAME meter concurrently could leave the durable `request.forecast[meter]` reflecting the
  earlier-appended event rather than the last. The forecast write is now folded into `record_event`
  under its single lock hold: it redacts once, appends, and — on a valid `_parse_forecast_event`
  triple — updates `self.forecasts[meter]` and writes `request.json`, all before releasing the lock.
  The standalone `record_forecast` method and the second lock acquisition in `_consume_stdout` are
  removed, so nothing can re-acquire the non-reentrant lock or re-open the race, and the durable
  block always matches the last forecast event for a meter. Forecast shape, latest-per-meter-wins,
  distinct-meter accumulation, malformed-skip, and secret redaction (parsed from the redacted event)
  are unchanged. Covered by `tests/core/test_forecast_ordering.py` (incl.
  `::test_concurrent_same_meter_forecasts_match_the_last_event`, 32 barrier-synced threads).
  _Source: C-2 review B; closed by this PR._
- **H10 — OpenRouter `usage.cost` is surfaced but not metered** (resolved by C-1). `_post_chat_completion`
  emits a `cost` event `{t:cost, meter:openrouter, unit:usd, amount:<usage.cost>, cached:false}` when
  `usage.cost` is a usable finite non-negative number, and the supervisor aggregates those events into
  `video.json`'s `cost` block (`actual` = non-cached sums, `uncached` = all sums, per meter). Dry-run
  still emits none (free, no network). Higgsfield per-video cost remains H20 (no per-call cost from its
  API). _Source: B-4c, deferred by design (PR #30); closed by C-1._
- **Higgsfield poll dropped auth** (resolved by the smoke_higgsfield increment). `media.video.generate`
  polled `GET {status_url}` (`/requests/{id}/status`) with no `Authorization` header, but that endpoint
  inherits the API's `Key id:secret` auth — so a PAID submit would succeed (credits spent) and every
  poll would 401, wasting the spend. Found by decorrelated Review B against the live OpenAPI; fixed to
  send `Authorization: Key <id:secret>` on the poll (submit already did; the result download stays
  headerless — `video.url` is an external pre-signed URL). Covered by
  `test_video_higgsfield.py::test_generate_real_poll_carries_auth`.
- **H21 — fail-open-when-unset** (resolved by the H21 increment). A real (non-dry) paid provider call
  with no budget configured is now refused at `Context._budget_reserve` (raises `BudgetError`, mapped to
  `stopped-budget` by T2b-2c) instead of passing through ungated. Enforced at the reserve site (after the
  key read, non-dry path only); passthrough contract reversed, three real-adapter integration suites
  migrated to a permissive budget, secret suites untouched.
- **H50 — non-auth error bodies still surfaced verbatim** (follow-up from TASK-Ph1; security-auditor
  advisory, non-blocking). TASK-Ph1 scrubbed the reflected credential from 401/403 error detail in
  `_http.request()` — the observed live leak. Two defence-in-depth gaps remain, deliberately left for
  a later increment because TASK-Ph1 preserves 400/5xx bodies for diagnostics on purpose: (a) a
  provider that reflects the `Authorization` header on a 400/402/5xx would still leak the key via
  `detail=_truncate(response.text)` — prefer redacting a known credential-token pattern from ALL
  non-2xx bodies (keeps diagnostics, fails safe) over status-gating; (b) 407 Proxy-Authentication is
  not in the fixed-detail branch (low risk — reflects proxy creds, not the submitted API key).
- **H51 — BFL API key egresses to the provider-returned polling_url host** (from TASK-Pb;
  security-auditor advisory, non-blocking). The BFL region-routing fix polls the absolute
  `polling_url` from the submit response, and `_http.request()` merges the `x-key: BFL_API_KEY`
  header onto every request — so the key now goes to whatever host BFL's response names (a real
  posture change vs the old base_url-pinned relative path; the `result.sample` download carries no
  auth, so this is the first provider-returned absolute URL to receive the secret). MITM-gated
  under the trusted-first-party model, hence advisory. Fix: before polling, assert `polling_url` is
  https and its host is `*.bfl.ai` (a small BFL region allowlist), reject otherwise — preserves the
  region fix while keeping the key on BFL-designated hosts. Do as a RED-first follow-up increment.
- **H52 — budget reserve-release on failure understates a bills-then-errors provider** (from
  TASK-Ph; security-auditor advisory, non-blocking). The reserve-release fix reconciles a failed
  paid call to `actual=0.0`. This is correct for the common case (the call failed before the
  provider billed) and closes the leak that over-counted per_day. But if a provider bills
  internally and THEN raises before returning a cost, releasing to 0 *understates* real spend
  (permissive — under-counts, lets more through) vs the old behaviour which over-counted. No cost
  is known at raise time, so this is inherent to the narrowed design. Options if it ever matters:
  release at-adapter failures to the *estimate* (fail-closed on money, but re-introduces the
  accumulation the fix removed) or add a "released-uncertain" ledger kind that still counts toward
  per_day. Related functional edge (not a defect): if `write_bytes` fails after `record_cost`, the
  real charge is recorded with no artifact on disk (an orphaned but truthful charge).
- **H53 — BFL host guard residuals** (from H51; security-auditor advisories on the merged guard,
  non-blocking). (a) *Parser differential*: `_require_bfl_host` validates the polling_url host with
  `urllib.urlsplit`, but the actual GET is issued by `httpx2`'s own URL parser; if the two ever
  disagreed on the authority for some exotic input the allow-list could be bypassed. All dangerous
  cases tested resolve correctly under both; to fully close the theoretical gap, pass the
  already-validated host to the request or re-check `response.request.url` after the call. (b) The
  `result.sample` image is fetched via `download_bytes` with no host restriction — it carries NO
  auth header (so not credential egress), but it is an attacker-influenceable outbound GET (minor
  SSRF surface); pre-existing, not introduced by H51. Both low risk, recorded for a future pass.
- **H54 — `_http._redact` residuals** (from H50; two reviewers, advisory, non-blocking). (a)
  *Empty-token mangling*: a scheme auth value with an empty token (e.g. `BearerAuth("")` →
  `"Bearer "`, reachable only with a set-but-empty credential) yields an empty post-scheme token, and
  `str.replace("", ...)` would garble the diagnostic body by inserting `[redacted]` between every
  character. No credential leaks (there is none) and it is near-unreachable in practice (an empty key
  almost always returns 401, which takes the fixed-string path, not the redact path). Trivial guard:
  skip empty split tokens (`if token := value.split(" ", 1)[1]: secrets.add(token)`). (b)
  *Non-verbatim reflection*: `_redact` is exact-match, so a credential the server echoes re-encoded /
  case-folded / whitespace-split survives — acceptable given high-entropy alphanumeric tokens and the
  declared "precise, only-what-we-sent" boundary. Fold the guard in next time `_http.py` is touched.
- **H55 — `agents.llm` image-attachment controls** (from TASK-agents-vision). Originally three
  advisories on the multimodal fix; cross-family Review B escalated them because `agents.llm` reads a
  caller-named path and EGRESSES its bytes to OpenRouter, so they are now ENFORCED controls in
  `agents.llm` (validated before any read/network, each raising `ValueError`): (a) *Suffix
  allow-list, on the resolved target* — the `image/png` fallback is removed; a suffix not in
  `_IMAGE_MIME` is rejected, and the suffix is taken from the RESOLVED path (`resolved.suffix`) not
  the symbolic name, so a within-workspace symlink `masq.png` → `secret.env` is rejected on `.env`
  rather than egressing non-image bytes mislabeled as an image. A non-image (incl. a video clip, or
  `context.json`/`.env`) is never shipped. (b)
  *Bounds* — a per-attachment size ceiling (`_MAX_ATTACH_BYTES`, `stat()` checked before
  `read_bytes()`) and a per-call count ceiling (`_MAX_ATTACH_COUNT`) bound memory and payload. (c)
  *Path containment* — each path resolves under `ctx.paths.video` and must satisfy
  `resolved.is_relative_to(ctx.paths.video.resolve())` and `is_file()`; `.resolve()` collapses `..`
  and follows symlinks, so an absolute path, a `..` escape, or a symlink leaving the workspace is
  rejected, and bytes are read from the validated `resolved` (not the raw join). (d) *Snapshot* — the
  input is materialised to `items = tuple(attach)` before the count gate, so a sequence whose
  `__len__` disagrees with iteration cannot bypass the ceiling.
  **Accepted residuals (advisory, within the trusted-workflow threat model — a workflow is trusted,
  unsandboxed Python, so a self-inflicted odd input is out of the threat model):**
  (i) *Suffix, not content* — the allow-list judges the file suffix, not the file's magic bytes, so a
  non-image deliberately named `x.png` by the workflow is still uploaded (the provider rejects a
  non-image anyway). Content-type sniffing is deferred as defense-in-depth; the suffix-only contract
  is the agreed model. (ii) *Pathological caller sequences* — `if attach:` truthiness means a
  nonempty sequence with a falsy `__len__`/`__bool__` is treated as no-attach (text-only, no egress),
  and `tuple(attach)` fully materialises a caller iterator before the count gate (a giant iterator
  costs transient memory ~ its size); both are self-inflicted by a trusted workflow and harmless.
  (iii) *TOCTOU* — a `stat`-vs-`read` window remains, acceptable under the trusted-workflow model.
  **Separate pre-existing issue (NOT part of this feature, tracked as its own task):**
  `agents._post_chat_completion` reserves budget (`ctx._budget_reserve`) then, on a 402 / other non-2xx
  / retries-exhausted, raises WITHOUT `ctx._budget_reconcile`, leaking the reservation toward the
  per-day ceiling (the H52 class, on the agents.llm paid path; affects ALL `llm()` calls, not just
  vision). It is unchanged by TASK-agents-vision — vision only makes provider errors more likely to
  surface it. Fix in its own increment: reconcile (release) the reserve on every non-success exit.
  **Cross-cutting note:** `media/image.py` and `_refs.py` still resolve refs on the accepted
  trusted-workflow model (they also egress refs to the provider); extend the same confinement +
  suffix guard to them in the Phase 4 refactor pass for consistency.
- **H56 — Openverse commons adapter: malformed-200 hygiene** (web-sourcing increment 2;
  security-auditor advisory, non-blocking). **MOSTLY CLOSED at increment-2 round 2:** the adapter now
  routes through `_http.parse_json` (non-JSON / non-dict body → `AdapterError`), tolerates a
  missing/null `results` (`data.get("results") or []`), skips non-dict rows and null-`url` results, and
  coerces null string fields — the earlier raw `resp.json()`/`r["url"]`-KeyError/`AttributeError` crash
  paths are gone. **Residual (open, low, trusted-upstream):** `int(r.get("width") or 0)` /
  `int(r.get("height") or 0)` still raise `ValueError`/`TypeError` on a malformed 200 where
  `width`/`height` is a non-numeric string or non-scalar (Openverse's schema types these as int, so
  real data is safe). Close with a defensive `_as_int(x, default=0)` (catch `TypeError`/`ValueError`)
  when the fetch/parse path is next touched (increment 3). Change-log nit: the `openverse` METERS row
  is `fiat/usd` though the commons tier is free/keyless (no spend recorded); it fits the eventual paid
  web tier — revisit the meter model if the paid tier lands separately.
- **H57 — `media.web.fetch` SSRF-guard residuals** (web-sourcing increment 3a; security-auditor
  advisories after the guard PASSED — the IPv6-embedded-IPv4 bypass and unbracketed-IPv6 bug were
  fixed and are NOT residual; these are non-blocking hardening notes). (a) *Host header carries
  userinfo/port verbatim* — the pinned request sets `Host: parts.netloc`, so a `user:pass@host` URL
  emits a malformed Host header (and echoes any credentials to the pinned host). Immaterial for the
  commons tier (Openverse returns clean CDN URLs) but should use `parts.hostname` (+ non-default port)
  before the UNTRUSTED web tier (increment 6) lands. (b) *Arbitrary port on a public host* —
  `port = parts.port or 443` allows connecting to any port of a validated-public host (not an internal
  SSRF vector; the IP is `is_global`). An allow-list to 443 would be tighter; weigh against breaking a
  legit non-443 image URL. (c) *6to4 (2002::/16) / Teredo (2001::/32) / RFC 8215 local-use NAT64
  (64:ff9b:1::/48) / site-local (fec0::/10) / reserved* — CLOSED, version-independently. These IPv6
  forms embed or route to a private/internal target; CPython 3.12.0-3.12.3 misclassify several as
  `is_global=True`. Cross-family Review B (PR #142) showed a version floor alone is NOT sufficient:
  `app/core/env.py` reuses a cached workflow venv on a requirements-hash match without rechecking the
  interpreter or reinstalling the editable SDK, so new fetch code can run on a pre-3.12.4 interpreter.
  Fixed in `media.web` (increment 3a-r2) by explicit, `is_global`-independent handling: `_public_addr`
  unwraps 6to4 (embedded IPv4 at bytes 2-6) so the embedded address is validated; and the guard
  rejects Teredo `2001::/32`, local-use NAT64 `64:ff9b:1::/48`, `is_site_local`, and `is_reserved`
  addresses by explicit membership/property. `requires-python >=3.12.4` (sdk/pyproject.toml) is
  retained as defense-in-depth but is no longer load-bearing. The well-known NAT64 `64:ff9b::/96` and
  IPv4-compat `::/96` forms stay `is_global=True` even on current CPython and remain explicitly
  unwrapped-and-validated in `_public_addr`. (d) *Nondeterministic pin ordering* — `ips[0]` depends on getaddrinfo order; not a hole (all
  resolved IPs are validated). (e) *64-bit content-hash* (`_content_hash` = sha256[:16]) — collision
  risk only; this is the increment-3b hash-widening commitment, recorded there.
- **H58 — cached workflow venvs do not re-validate the interpreter or reinstall on an SDK security
  fix** (surfaced by cross-family Review B while reviewing the media.web SSRF guard, PR #142; broader
  than that guard). `app/core/env.py::ensure_env` returns a cached venv whenever the workflow's
  `requirements.txt` hash matches, without rechecking the interpreter version or reinstalling. Because
  the SDK is installed editable (`pip install -e`), a venv keeps whatever interpreter first created it
  (e.g. a pre-`requires-python`-floor Python) while immediately picking up new SDK source — so a
  security fix or a raised `requires-python` floor does NOT propagate to existing cached venvs, and an
  out-of-floor interpreter can keep running new code. The media.web guard was made interpreter-version
  independent (H57(c)) so this does not leave a live SSRF hole, but the general patch-propagation gap
  remains: consider folding the SDK version (or `requires-python`) into the venv cache key, or
  recording the creating interpreter in the hash marker and invalidating on mismatch. Address before
  the SDK is relied on as a security boundary across long-lived cached environments (revisit with the
  untrusted web tier, increment 6). Owner FYI.
- **H23 — `BudgetGuard` read methods leak non-`BudgetError` from a poisoned ledger** (resolved by this
  PR). `reserve`/`day_total`/`run_total` now fail closed as `BudgetError`: `_read_ledger` wraps
  `OSError` (in addition to decode/JSON faults), and `_snapshot` wraps `ValueError`/`OverflowError`
  from a valid-JSON-but-non-numeric or overflowing `amount`. Argument validation on
  `reserve(estimate=…)` / `reconcile(actual=…)` still raises raw `ValueError`. `read_run_spend` stays
  best-effort. Covered by
  `tests/sdk/test_budget.py::test_a_bad_amount_on_a_valid_json_line_fails_closed_as_budgeterror`.
  _Source: T2b-2c review B (High #3); closed by this PR._
- **H28 — atomic pre-flight raises on an unreadable ledger instead of a controlled refusal** (resolved
  by this PR). `check_atomic_budget` now catches `BudgetError` from `run_total`/`day_total` and
  returns `budget ledger unreadable, refusing to start atomic run: {exc}` so a poisoned ledger
  refuses the run instead of propagating out of `run_request` and stranding it `running`. Existing
  headroom messages and the empty-estimate → None contract are unchanged. Covered by
  `tests/core/test_preflight.py::test_check_atomic_budget_refuses_on_a_poisoned_ledger`.
  _Source: C-4 review B (P2); closed by this PR (with H23)._
- **H59 — `_token_states` silently skips a reserved/actual line missing its token** (resolved by this
  PR). A `reserved`/`actual` ledger line without a token is corruption (the engine always writes one);
  skipping it under-counts spend and lets a later reserve overshoot. `_token_states` now raises
  `BudgetError("budget ledger spend entry is missing its token")` for those lines. A non-spend
  token-less line is still skipped. `_snapshot` does not catch `BudgetError`, so the refusal
  propagates; `read_run_spend` stays best-effort. Covered by
  `tests/sdk/test_budget.py::test_a_spend_record_missing_its_token_fails_closed`.
  _Source: H23 completeness review; closed by this PR._
- **H22 — budget ledger keyed spend by a run_id that is only per-workflow-unique** (resolved by this
  PR). Two *different* workflows started in the same UTC second share a `run_id` (`allocate_run`
  suffixes for collisions only within one workflow's runs dir); the machine-wide ledger then merged
  their per-run spend. Every ledger entry now carries a `workflow_id`, and `_run_sum` /
  `read_run_spend` / `reserve` / `run_total` / `check_atomic_budget` key per-run accounting by
  `(run_id, workflow_id, meter)`. `workflow_id` is read tolerantly (absent → `""`, the legacy
  namespace) and is a keyword-only param defaulting to `""`, so pre-H22 durable ledgers and existing
  callers are unaffected; the production sites (supervisor `read_run_spend`/`check_atomic_budget`,
  `Context._budget_reserve`, learning `make_openrouter_completion`) pass the real id. `day_total`
  stays a global per-day cap. `run_id` generation and the run-dir layout are unchanged. Covered by
  `tests/sdk/test_budget.py::test_run_total_isolates_two_workflows_sharing_a_run_id`,
  `::test_read_run_spend_isolates_two_workflows_sharing_a_run_id`,
  `::test_reconcile_preserves_workflow_id_isolation`,
  `::test_legacy_ledger_line_without_workflow_id_totals_in_the_default_namespace`, and
  `tests/core/test_preflight.py::test_per_run_headroom_isolates_a_sibling_workflow_sharing_the_run_id`.
  _Source: T2b-2c review B; closed by this PR._
- **H60 — a non-string `meter` on a spend line silently under-counted** (resolved by this PR). A
  valid-JSON `reserved`/`actual` ledger line whose `meter` was present but not a usable string passed
  through `_as_str` → `""` and dropped out of `_run_sum`/`_day_sum` (spend under-count). The engine
  always writes a string meter, so a non-string/missing/empty meter is corruption; `_token_states`
  now raises `BudgetError("budget ledger spend entry has an invalid meter")` for those lines, uniform
  with the missing-token (H59) and bad-amount (H23) checks. (The malformed-`ts` and non-string
  `run_id`/`workflow_id` cases stay tolerated: `ts` is the documented H19 acceptance, and
  `workflow_id` must read tolerantly for pre-H22 ledger compatibility.) Flagged by the H23 security
  review (attribute-corruption residual); covered by
  `tests/sdk/test_budget.py::test_a_non_string_meter_on_a_spend_line_fails_closed`.
  _Source: H22 security review; closed by this PR._
- **H18 — failed-prepare `result.json` secret exposure** (resolved by this PR). `_run_prepare`
  redacted `result.json` only on the SUCCESS path, so a `prepare()` that wrote `shared/result.json`
  with an injected secret VALUE then exited non-zero left the secret on disk — in a file that, unlike
  `context.json`, was **downloadable** via `get_run_file`. Closed on two layers: **(1) the download
  exfil vector** — the engine's prepare output at `shared/result.json` is never served: `get_run_file`
  returns 404 for that exact (canonicalised, symlink-safe) path and `list_run_files` excludes it, so
  it cannot be downloaded regardless of the bytes/encoding a workflow wrote (byte-level value
  redaction alone could not cover every encoding — a UTF-16 `result.json` decodes back to the secret).
  The block is PATH-scoped to `shared/result.json` (not the basename), so a workflow's own artifact
  that merely shares the name stays served. The engine reads `shared/result.json` from disk directly,
  not via the endpoint, so this does not affect it. **(2) On-disk defence-in-depth** — a best-effort
  `_scrub_result_secrets` runs in the `_run_prepare` `finally` on every exit path, redacting
  `result.json` for any payload (reads raw bytes; structured JSON redaction primary, byte-level
  fallback stripping each secret's plain and JSON-escaped forms on an unparsable/undecodable/deeply
  nested file); it never raises during teardown. Covered by
  `tests/api/test_secret_exposure.py::test_shared_result_json_is_not_downloadable`,
  `tests/core/test_secret_redaction.py::test_scrub_result_secrets_*` (redaction, non-object payloads,
  pathologically nested, invalid UTF-8, JSON-escaped fallback, missing/bad file), and
  `::test_failed_prepare_result_secret_is_redacted_on_disk_and_download`. Residuals recorded
  separately: H61 (`artifacts/**`, `.steps/**` served without redaction), H62 (success-path re-parse
  crash on a pathological return). _Source: S2c review B residual note (PR #37); closed by this PR._
