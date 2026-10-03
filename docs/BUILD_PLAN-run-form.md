# Build plan — Run form + cost surfacing (audit fix F3)

Scope: PRD §8.2 (settings pop-up), §7.2 (how a budget is spent), §7.3 (estimating cost), §12 (disk).

Methodology: RED-first per increment — supervisor authors frozen tests → confirm RED → brief (`Satisfies: R-nnn`) → delegate to the resolved builder → Review A (opus `diff-reviewer`; + `security-auditor` on money/upload surfaces; + `design-auditor` on UI) + cross-family Review B → CI gate → self-merge. Briefs state the RED-first methodology so supervisor-added frozen tests are not misread as gate-gaming. Numeric-parsing briefs state "reject bool before int" (builder blind spot). PR titles start with the increment IDs (bridge 2026.09.27c), so `plan-check.py` derives status from `origin/main`. The project has no diagram index (designed before diagram-based planning), so every increment's `Diagrams:` is `none`.

## Owner decisions (2026-10-03)

- **R-024 budget = per meter, per Generation Request** (option A). One line per active meter capping that meter's total spend for the whole request, pre-filled from the estimate. It **replaces** the current single `per_video_budget` number, which sums every meter's spend for a video regardless of unit. The old per-video frozen tests (tests/sdk/test_budget_per_video.py, tests/sdk/test_ctx_per_video_budget.py, and the per_video_budget cases in tests/api/test_run_settings_*.py, tests/sdk/test_context_run_settings.py, frontend RunLaunchForm.test.tsx) are retired by the supervisor as part of TASK-103 because the requirement changed — not by the builder.
- **R-035 provider balance = build where possible.** Only where the key the app already holds can read a balance; providers without one (or billed postpaid) are listed in the brief as "no check — reason".

## Done before this plan used placement fields (merged)

| Inc | What | Satisfies | PR |
|---|---|---|---|
| F3-1 | `POST /api/workflows/{id}/estimate` per-meter estimate | R-032 | #182 |
| F3-3 | Estimate panel in the launch form | R-032 | #183 |
| F3-4/5 | Launch preflight: disk < 5 GB refuse (ancestor-volume aware), missing key, missing program | R-034, R-036 | #184 |

## Stage F3 — Run form + cost surfacing

A vertical slice: each pair below crosses the launch API, the SDK/run where needed, and the launch form, so the owner sees each setting work end to end.

### TASK-101 — Launch API: per-request dry run, parallel steps, max-videos cap (F3-6a)
- Parent: none
- Depends on: none
- Parallel: no
- Satisfies: R-023, R-027, R-028
- Diagrams: none
- Scope: app/api/runs.py, app/api/workflows.py

`LaunchBody.dry_run` (strict bool, default false) and `LaunchBody.step_concurrency` (int ≥ 1 or null → the Settings default; bool rejected before int) reach `admit_run`; `video_count` rejects bool; 422 when `video_count > manifest.workflow.max_videos`, before the preflight; `WorkflowOut.max_videos` exposed. Frozen tests: tests/api/test_launch_chassis.py. PR #185.

### TASK-102 — Launch form: chassis controls, decimal point, remembered values, last-known options (F3-6b)
- Parent: none
- Depends on: TASK-101
- Parallel: no
- Satisfies: R-019, R-021, R-023, R-027, R-028, R-030
- Diagrams: none
- Scope: frontend/src/components/RunLaunchForm.tsx, frontend/src/components/WorkflowCard.tsx, frontend/src/types.ts, frontend/src/api.ts, frontend/src/index.css

Dry-run checkbox; "Parallel steps per video" seeded from the Settings default; the video-count input capped by `maxVideos` (passed from `workflow.max_videos`); `number` params as text inputs with `inputMode="decimal"`, point-only; the last successful start remembered per workflow in localStorage (`sfvf.launchForm.<id>`, try/catch, defaults on failure, wins over Settings seeding); each options fetch cached (`sfvf.providerOptions.<source>`) and offered with a "last known" warning when a later fetch fails. Frozen tests: frontend/src/components/RunLaunchForm.chassis.test.tsx.

### TASK-103 — Per-meter, per-request budget in the run (F3-7)
- Parent: none
- Depends on: TASK-101
- Parallel: no
- Satisfies: R-024
- Diagrams: none
- Scope: app/api/runs.py, app/core/supervisor.py, sdk/sfvf/context.py, sdk/sfvf/_budget.py

`LaunchBody.budget: {meter: amount}` replaces `per_video_budget`; carried to the Context; BudgetGuard enforces each line as a request-scoped per-run ceiling (effective = min(global per_run, request line)); a request line counts as a ceiling for the per-call-estimate check; amounts finite > 0, bool rejected; the per-video single-number ceiling is removed.

### TASK-104 — Budget lines in the launch form (F3-8)
- Parent: none
- Depends on: TASK-102, TASK-103
- Parallel: no
- Satisfies: R-024
- Diagrams: none
- Scope: frontend/src/components/RunLaunchForm.tsx, frontend/src/types.ts, frontend/src/api.ts, frontend/src/index.css

One line per meter from the estimate, pre-filled with the estimate amount and unit, point-only decimals, blank = no request cap; the old "Per-video budget (USD)" field is removed.

### TASK-105 — Read-only settings view for a running request (F3-9)
- Parent: none
- Depends on: TASK-104
- Parallel: no
- Satisfies: R-031
- Diagrams: none
- Scope: frontend/src/components/RunLaunchForm.tsx, frontend/src/components/WorkflowCard.tsx, frontend/src/types.ts, frontend/src/api.ts, app/api/runs.py

A running card offers "View settings", which opens the form read-only, filled from the run record; no editable launch form while a request runs.

### TASK-106 — File setting: picker and safe upload (F3-10)
- Parent: none
- Depends on: TASK-102
- Parallel: no
- Satisfies: R-016
- Diagrams: none
- Scope: frontend/src/components/RunLaunchForm.tsx, frontend/src/api.ts, frontend/src/types.ts, app/api/runs.py, app/paths.py

A file picker honouring the param's `accept`; an upload route that stores the file in the request's input area and returns a safe path; a size cap; no path traversal.

### TASK-107 — Provider-balance launch check where the held key can read a balance (F3-11)
- Parent: none
- Depends on: TASK-101
- Parallel: no
- Satisfies: R-035
- Diagrams: none
- Scope: app/api/runs.py, app/core/balances.py

Research 2026-10-03 (documentation only): **BFL** `GET api.bfl.ai/v1/credits` (`x-key`; `credits`, 1 = $0.01); **SerpApi** `GET serpapi.com/account.json` (`total_searches_left`, free call); **OpenRouter** `GET /api/v1/key` `limit_remaining` only when the key has a cap (null → skip; the account `/credits` needs a management key the app does not hold). Refuse when the balance is below this request's estimate for that meter, naming the provider and the shortfall; an unreachable or unparseable balance call degrades to non-blocking. Per rule 37 the first step is a contract capture of each balance endpoint's real response (attended, owner's keys, free calls), recorded as fixtures the tests replay. No check, recorded in the brief: BytePlus (needs IAM AK/SK + request signing), Google (postpaid), OpenAI (admin key, spend not balance), MiniMax pay-as-you-go (no API).

## Moved

- **R-025 Maximum retries** moves to **F4** with R-105 (retry behaviour) and R-106 (recovery pop-up): the setting is meaningless without the retry loop, and building them together keeps one frozen contract.
- **R-072 / R-158 disk 20 GB warn** go to **F4** (reliability); the 5 GB refuse half shipped in F3-4/5.

## Traceability

R-016, R-019, R-021, R-023, R-024, R-027, R-028, R-030, R-031, R-032, R-034, R-035, R-036 are covered above. R-025, R-072, R-158 are planned in F4 (see the F4 plan when written).
