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

## Open

- **H1 — GSAP loaded from CDN at render time.** `media.graphics.render` fetches pinned `gsap@3.14.2` from
  jsDelivr while rendering — a live external call inside the otherwise zero-cost *local* renderer; offline
  renders would stall. Vendor/serve GSAP locally. _Source: B-1b review (PR #25)._ Open.
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
- **H6 — blocking local FFmpeg ops emit no heartbeats.** `media.edit.trim`/`cut` **and** `sfvf.finalize` run
  FFmpeg synchronously with no heartbeat, so the §2.8 300 s silence watchdog could kill a legitimately long
  encode/concat. Add periodic `ctx.heartbeat` (and/or honor a render-family `[[limits]]` cap) as **one
  consistent pass over both**, not a one-off in `edit`. _Source: B-2 review B (PR #26)._ Open.
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
  (PR #29)._ Open (low).

- **H11 — `agents.llm` trusts the OpenRouter 200 body shape.** `data.get("usage", {}).get("cost")` raises
  `AttributeError` if a 200 response carries `"usage": null` (key present, value null) rather than omitting it;
  likewise `data["choices"][0]["message"]["content"]` assumes a well-formed body. OpenRouter returns an object
  or omits the field, so this isn't hit in practice, but the adapter should defensively handle a malformed /
  null-usage 200 (treat missing/None usage as no-cost; raise a clear error on an unexpected body shape rather
  than an opaque `KeyError`/`AttributeError`). Extends to `agents.research`: a `url_citation` annotation whose
  inner object is missing `url` raises `KeyError` mid-parse rather than being skipped (`title`/`content` are
  already `.get`-defensive) — skip annotations without a `url`. _Source: B-4c review A + B-4d review A,
  non-blocking notes (PR #30, #31)._ Open (low).
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
  is the escape hatch meanwhile. _Source: B-5, dry_run/mocked (PR #33)._ Open (verify-before-live).
- **H14 — Higgsfield response robustness (429 retry + malformed 2xx body).** Non-2xx on submit, poll, AND
  download are now handled (each raises a labeled `RuntimeError`; a failed download never saves an error body
  as the video — B-5 review B P1/P2, fixed). Still open: (a) no `Retry-After`/429 backoff-retry (it queues
  behind the §5.5 limiter but doesn't `penalize`+retry like `agents._post_chat_completion`); (b) a well-formed
  2xx with an unexpected body shape (missing `request_id`/`status`/`video.url`) raises a bare `KeyError` rather
  than a clear adapter error. Add the 429-retry and defensive body parsing before any unattended live use.
  _Source: B-5 review A + B (PR #33)._ Open (low, pre-live).
- **H15 — Higgsfield frame/ref-conditioned generation not built.** `first_frame`/`last_frame`/`refs` raise
  `NotImplementedError`; image-to-video and first-last-frame endpoints (plus the image-upload mechanics and the
  `media.analyze.frame` clip-chaining path, §6.3/§6.3a) are a follow-up increment. _Source: B-5 (PR #33)._ Open.
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
- **H18 — failed-prepare `result.json` not redacted (residual).** S2c redacts the `prepare()` return payload and
  rewrites `shared/result.json` on the SUCCESS path, and redacts the per-video `result`→`video.json` path, so no
  injected secret VALUE persists into any consumed record. Residual (low): if a `prepare()` writes `result.json`
  and then exits non-zero, `_run_prepare` returns `False, None` before the redact/rewrite, leaving that
  failed-run `result.json` unredacted on disk — and (unlike `context.json`) it is downloadable via
  `get_run_file`. Same defect class as the closed success-path leak; narrow trigger (prepare must both leak its
  key into `result.json` AND fail after writing it). Fix: redact `result.json` best-effort in the `_run_prepare`
  `finally` (covering both paths uniformly), or block `result.json` download alongside `context.json`.
  _Source: S2c review B residual note (PR #37)._ Open (low, residual).
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
- **H22 — budget ledger keys spend by a run_id that is only per-workflow-unique.** `allocate_run`
  (`app/core/ids.py`) suffixes for collisions only within one workflow's runs dir, so two *different*
  workflows started in the same UTC second share the same `run_id`. The ledger is machine-wide, and both
  the gate's per-run accounting (`_run_sum`) and T2b-2c's `read_run_spend` filter by `run_id`+`meter`
  only — so those two runs' spend merges, over-counting each other's per-run ceiling and cross-reporting
  spend. Pre-existing to the T2a engine; `read_run_spend` faithfully mirrors the gate's own filter (fixing
  one without the other would desync them). Fix: namespace ledger entries by `workflow_id` (write+filter),
  or make `run_id` globally unique. Low likelihood (same-second cross-workflow starts), report/accounting
  accuracy only — never authorizes extra spend (ceilings only tighten under a merge). _Source: T2b-2c
  review B._ Open.
- **H23 — `BudgetGuard.reserve` can leak non-`BudgetError` exceptions from a poisoned ledger.** During a
  reserve, the engine re-reads the ledger; a valid-JSON line with a bad/overflowing `amount` raises
  `ValueError`/`OverflowError` (and a read fault `OSError`) straight out of `reserve()`, not wrapped as a
  `BudgetError`. The runner's `_budget_reason` keys on `BudgetError`, so such a corruption-driven refusal
  is labeled generic `failed` rather than a budget stop — arguably correct (a corrupt ledger is infra, not
  exhaustion, and a top-up won't fix it), but the engine's public methods should be uniformly
  fail-closed-as-`BudgetError` so callers get one refusal type. Fix in the T2a engine: wrap ledger-parse
  errors inside `reserve`/`day_total`/`run_total` as `BudgetError`. (T2b-2c's report read is already fully
  best-effort and unaffected.) _Source: T2b-2c review B (High #3, de-scoped from the label increment)._ Open.
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
  `{failed,nsfw,canceled}` terminal set. _Source: Higgsfield API verification (step-4 prep)._ Open.
- **H26 — forecast latest-per-meter is not strictly event-ordered across concurrent videos (C-2).**
  `record_event` (append) and `record_forecast` (accumulator + request.json write) take the run lock
  separately, so if two videos in one request forecast the SAME meter concurrently, the durable
  `request.forecast[meter]` may reflect the earlier-appended event rather than the last one. Accepted
  as low-impact: forecasts are soft, non-blocking, informational reservations; the consumer (C-3
  atomic pre-flight) applies to atomic single-episode workflows where there is no intra-request
  concurrency; and "latest across independent concurrent video threads" is itself ill-defined. A
  strict fix would fold the forecast accumulator update into `record_event` under one lock hold; do
  that only if a real multi-video-same-meter forecasting workflow appears. _Source: C-2 review B._ Open.
- **H27 — cost estimate is a per-run total, not per-video scaled by the requested count (C-4).**
  `estimate_cost` averages each historical run's **summed-over-videos** uncached cost, and the atomic
  pre-flight compares that to the budget without scaling by the run's requested `video_count`. Two
  consequences: (a) a run requesting more videos than history typically produced is under-estimated
  (and could be admitted over the per-run ceiling), and fewer is over-estimated; (b) including
  `partial` runs (mandated by the C-4 contract) sums every video record in that run — `_run_uncached`
  does not filter to `video.status == "complete"` — so cost from videos that did not finish leaks into
  the average. Both are the same root: the estimator has no per-video unit. Backstopped by the live
  BudgetGuard reservation, which still refuses each actual paid call past a ceiling mid-run, so this
  cannot cause overspend beyond the ceilings — it only weakens the pre-flight's "don't even start"
  guarantee for multi-video atomic runs (of which there are none in production today). Fix as a
  deliberate estimator-semantics increment (also feeds the C-5 Statistics tab): estimate per-video
  uncached cost over `complete` videos only, expose the per-video figure, and multiply by the
  requested `video_count` in the pre-flight (scale `estimate.per_meter` before `check_atomic_budget`,
  keeping its frozen signature). The frozen C-3/C-4 tests use one-video runs, so per-run == per-video
  there and they remain valid. _Source: C-4 review B (P1 video_count + P2 partial-video cost)._ Open.
- **H28 — atomic pre-flight raises on an unreadable ledger instead of a controlled refusal (C-4).**
  `check_atomic_budget` calls `guard.run_total`/`day_total`, which today propagate a ledger-parse/IO
  error rather than a `BudgetError`; on such an error the pre-flight would raise out of `run_request`
  after the request was already written `running`, leaving it stuck. This is the same engine gap as
  **H23** (make the `BudgetGuard` read methods uniformly fail-closed as `BudgetError`) now with the
  pre-flight as an additional caller; resolving H23 resolves this. Until then the exposure is a
  corrupt/permission-denied ledger file, which equally affects the reservation path. _Source: C-4
  review B (P2); see H23._ Open.
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
  already hides them). _Source: E-4a diff-reviewer + security-auditor ADVISORY/NOTED._ Open.

## Resolved

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
