# Build plan — Run form + cost surfacing (audit fix F3)

Scope: PRD §8.2 (settings pop-up), §7.2 (how a budget is spent), §7.3 (estimating cost), §12 (disk).
Methodology: RED-first per increment — supervisor authors frozen tests -> confirm RED -> brief
(`Satisfies: R-nnn`) -> delegate to composer-2.5 -> Review A (opus diff-reviewer; +security-auditor on
money/upload surfaces; +design-auditor on UI) + cross-family Review B (grok-4.7-high) -> CI gate ->
self-merge. Briefs state the RED-first methodology so supervisor-added frozen tests are not misread as
gate-gaming. Numeric parsing briefs state "reject bool before int" (builder blind spot).

## Owner decisions (2026-10-03)
- **R-024 budget = per meter, per Generation Request** (option A). One line per active meter capping that
  meter's total spend for the whole request, pre-filled from the estimate. It **replaces** the current
  single `per_video_budget` number, which sums every meter's spend for a video regardless of unit.
  The old per-video frozen tests (tests/sdk/test_budget_per_video.py, test_ctx_per_video_budget.py and the
  per_video_budget cases in test_run_settings_*.py / test_context_run_settings.py / RunLaunchForm.test.tsx)
  are retired by the supervisor as part of F3-7 because the requirement changed — not by the builder.
- **R-035 provider balance = build where possible.** Check each current provider for a documented balance
  API callable with the key the app already holds; build the launch refusal only for those. Providers
  without one (or billed postpaid) are listed in the brief as "no check — reason".

## Done (merged)
| Inc | What | Satisfies | PR |
|---|---|---|---|
| F3-1 | `POST /api/workflows/{id}/estimate` per-meter estimate | R-032 | #182 |
| F3-3 | Estimate panel in the launch form | R-032 | #183 |
| F3-4/5 | Launch preflight: disk < 5 GB refuse (ancestor-volume aware), missing key, missing program | R-034, R-036 | #184 |

## Increments (remaining)
| Inc | What | Satisfies | Reviews |
|---|---|---|---|
| F3-6a | Backend chassis plumbing: `LaunchBody.dry_run` (bool, default False) passed to admit_run; `LaunchBody.step_concurrency` (int ≥1 or null → global default; reject bool); 422 when `video_count > manifest.workflow.max_videos`; `WorkflowOut.max_videos` exposed | R-023, R-027, R-028 | A + B |
| F3-6b | Form chassis controls: Dry-run checkbox, Parallel-steps input, video-count `max` from the manifest; point-only decimal entry regardless of locale; last-used values remembered per workflow (localStorage, try/catch, falls back to defaults); last-known option list shown with a warning when the options fetch fails | R-019, R-021, R-023, R-027, R-028, R-030 | A + design + B |
| F3-7 | Per-meter per-request budget (backend + SDK): `LaunchBody.budget: {meter: amount}` replaces `per_video_budget`; carried to the Context; BudgetGuard enforces each line as a request-scoped per-run ceiling (effective = min(global per_run, request line)); a request line counts as a ceiling for the per-call-estimate check; amounts finite > 0, bool rejected; per-video single-number ceiling removed | R-024 | A + security + B |
| F3-8 | Budget lines in the form: one line per meter from the estimate, pre-filled with the estimate amount + unit, blank = no request cap | R-024 | A + design + B |
| F3-9 | Read-only settings view: a running card offers "View settings" (opens the form read-only from the run record) instead of an editable launch form | R-031 | A + design + B |
| F3-10 | File setting: file picker honouring `accept`, upload route that stores into the run's input area and returns a safe path; size cap; no path traversal | R-016 | A + security + B |
| F3-11 | Provider-balance preflight, only where the held key can read a balance (research 2026-10-03, docs only): **BFL** `GET api.bfl.ai/v1/credits` (`x-key`; `credits`, 1 = $0.01); **SerpApi** `GET serpapi.com/account.json` (`total_searches_left`, free call); **OpenRouter** `GET /api/v1/key` `limit_remaining` only when the key has a cap (null → skip; the account `/credits` needs a management key we don't hold). Refuse when the balance is below this request's estimate for that meter, naming provider + shortfall; an unreachable/unparseable balance call degrades to non-blocking; tests use a stub transport, never real keys. **No check (recorded in the brief):** BytePlus (needs IAM AK/SK + signing), Google (postpaid), OpenAI (admin key, spend not balance), MiniMax pay-as-you-go (no API) | R-035 | A + security + B |

## Moved
- **R-025 Maximum retries** moves to **F4** with R-105 (retry behaviour) and R-106 (recovery pop-up): the
  setting is meaningless without the retry loop, and building them together keeps one frozen contract.
- **R-072 / R-158 disk 20 GB warn** go to **F4** (reliability); the 5 GB refuse half shipped in F3-4/5.

## Traceability
R-016, R-019, R-021, R-023, R-024, R-027, R-028, R-030, R-031, R-032, R-034, R-035, R-036 are covered
above. R-025, R-072, R-158 are planned in F4 (see the F4 plan when written).
