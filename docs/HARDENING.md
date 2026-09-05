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

- **H10 — OpenRouter `usage.cost` is surfaced but not metered.** `agents.llm` parses the real per-call
  `usage.cost` (and will estimate in dry_run) and surfaces it via a `ctx.log` line, but emits **no** cost/meter
  event — deliberately, because the budget-engine cost/meter schema is Stage C's and a provisional event now
  would only have to be migrated. Stage C must wire `usage.cost` (and the dry_run estimate) into the budget
  engine so spend is actually recorded/metered, not just logged. Applies to every priced provider adapter as
  they land. _Source: B-4c, deferred by design (PR #30)._ Open.

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

## Resolved

_(none yet)_
