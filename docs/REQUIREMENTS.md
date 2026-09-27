# Requirements — SFVF (Short-Form Video Factory)

Built retrospectively during the 2026.09.27b bridge calibration (rule 44 / KP-029), from the
requirements document (docs/SFVF_Project_Requirement_Document.md), the UI mockup
(docs/SFVF_UI_Mockup.html), the current change-cycle design docs
(docs/DESIGN-sensational-science-news.md, docs/DESIGN-web-image-sourcing.md,
docs/DELIVERY.md), docs/INVENTORY.md, and the shipped code + tests. Status is decided from
code and tests, not from the plan. Evidence names the test(s) that exercise a built
requirement (the requirement ID is threaded into those tests as increments touch them).

| ID | Requirement | Source | Status | Evidence |
|---|---|---|---|---|
| R-001 | Workflows are discovered automatically on disk (the `workflows/` folder) and listed. | requirements document §3.1(1), §8.1 | built | tests/api/test_workflows.py |
| R-002 | Workflows are displayed as a grid of cards on the Workflows (Main) tab. | requirements document §8.1; mockup screen "Workflows" | built | tests/api/test_workflows.py |
| R-003 | A "Rescan folder" control re-reads the workflows folder so an edited workflow is picked up without restart. | requirements document §8.1; mockup screen "Workflows" | built | tests/api/test_workflows.py |
| R-004 | Each workflow card shows the workflow title, description, and thumbnail (or an empty-thumb fallback). | requirements document §8.1; mockup screen "Workflows" | built | tests/api/test_workflows.py |
| R-005 | Each card shows the average cost per meter across the last 10 runs ("Average per video · last 10 runs"). | requirements document §8.1; mockup screen "Workflows" | planned | — |
| R-006 | A running card shows a yellow outline plus the stage the workflow reports (e.g. "3/7 — Generating shots"). | requirements document §8.1; mockup screen "Workflows" | planned | — |
| R-007 | Card outline colours indicate state: none=idle, yellow=running, green=finished (clears when the video list is opened), red=error. | requirements document §8.1 | planned | — |
| R-008 | A red outline appears only for errors needing attention; auto-recovered errors (retry-success, slow provider) stay silent. | requirements document §8.1 | planned | — |
| R-009 | A "Run workflow" button on each card opens the run configuration. | requirements document §8.1, §8.2; mockup screen "Workflows" | built | tests/api/test_run_settings_api.py |
| R-010 | Only one Generation Request may run per workflow at a time; a second launch is rejected as busy. | requirements document §8.1 | built | tests/api/test_runs.py |
| R-011 | A workflow whose code is deleted but whose output remains stays as a greyed-out archived card so its videos stay browsable. | requirements document §8.1 | planned | — |
| R-012 | The manifest identifier is permanent (links output folder); the display name may change freely. | requirements document §8.1 | built | tests/api/test_workflows.py |
| R-013 | Broken/invalid workflows are shown with an error state and their problem messages. | requirements document §8.1 (red/error state) | built | tests/api/test_workflows.py |
| R-014 | The Run configuration renders the workflow's own declared settings automatically from the manifest. | requirements document §8.2 | built | tests/api/test_run_settings_api.py |
| R-015 | The run form supports the declared setting types: single-line text, multi-line text, number, yes/no, single choice, multiple choice, and file. | requirements document §8.2 | built | tests/api/test_workflows.py (params schema); RunLaunchForm renders file as a plain text field |
| R-016 | The "file" setting type (reference media input) is accepted and rendered as a dedicated file picker in the run form. | requirements document §8.2, §13 | planned | — (accepted in schema and shown as a plain text field; a dedicated file picker is absent) |
| R-017 | A choice list may be supplied by a named provider source and filled in when the form opens. | requirements document §8.2 | built | tests/api/test_providers.py |
| R-018 | The chosen provider-supplied value is recorded as a pinned identifier so the run stays reproducible. | requirements document §8.2 | built | tests/api/test_providers.py |
| R-019 | If the provider cannot be reached, the last-known option list is offered with a note (fallback to manual entry). | requirements document §8.2 | planned | — (on fetch failure RunLaunchForm offers manual entry with a note, but no last-known list is retained; app/api/providers.py stores no previous list) |
| R-020 | Numeric settings are validated before the run starts, with the unit shown beside the field. | requirements document §8.2 | built | frontend/src/components/RunLaunchForm.tsx (unit via controlLabel; validation in collectParams) — a dedicated numeric-validation test is still to be added |
| R-021 | Decimal values use a point regardless of regional settings. | requirements document §8.2 | planned | — |
| R-022 | Chassis setting: Number of videos, per Generation Request. | requirements document §8.2 | built | tests/api/test_run_settings_api.py |
| R-023 | Number of videos is capped where the workflow declares a maximum. | requirements document §8.2, §5.1 | planned | — |
| R-024 | Chassis setting: Budget, with one line per active meter. | requirements document §8.2, §7.2 | planned | — |
| R-025 | Chassis setting: Maximum retries (default 3), set per Generation Request. | requirements document §8.2, §9.3 | planned | — |
| R-026 | Chassis setting: Concurrency (videos produced at the same time). | requirements document §8.2 | built | tests/api/test_run_settings_api.py (the "ignored for a sequence workflow" clause is tracked under R-082, planned) |
| R-027 | Chassis setting: Parallel steps per video (default 1). | requirements document §8.2 | planned | — |
| R-028 | Chassis setting: Dry run (fake assets, no spending) selectable per run from the form. | requirements document §8.2 | planned | — |
| R-029 | The run form offers an approval mode (require approval vs autonomous) mapping to gate auto-pass. | requirements document §9.6a; mockup "Run" modal | built | tests/api/test_gate_api.py; tests/core/test_supervisor.py |
| R-030 | Values used last time are remembered per workflow and pre-filled when the form is reopened. | requirements document §8.2 | planned | — |
| R-031 | Once a Generation Request starts, its settings are fixed; the pop-up can still be opened read-only from a running/paused card. | requirements document §8.2 | planned | — |
| R-032 | When the form is open, a cost estimate is shown for each meter. | requirements document §8.2, §7.2 | planned | — |
| R-033 | Initiate is blocked with a specific message when a declared capability is not offered by any configured provider. | requirements document §8.2, §6.5 | built | tests/api/test_admission_model_config.py |
| R-034 | Initiate is blocked with a specific message when a required key/connection is missing or a required program is not installed. | requirements document §8.2 | planned | — |
| R-035 | Initiate is blocked when provider balances are insufficient. | requirements document §8.2, §7.2 | planned | — |
| R-036 | Initiate is blocked when free disk space is below the hard floor (5 GB). | requirements document §8.2, §8.7 | planned | — |
| R-037 | A workflow may offer a setting to specify the topic or leave it to the research agent; an AI-chosen topic is chosen once per request. | requirements document §8.2 | built | tests/integration/test_ssn_script.py |
| R-038 | Clicking a card opens a video list pseudo-tab (closable, returns to prior scroll position). | requirements document §8.3; mockup pseudo-tab "video list" | planned | — |
| R-039 | The video list shows every video the workflow produced, grouped by Generation Request with a divider between groups. | requirements document §8.3; mockup pseudo-tab "video list" | planned | — |
| R-040 | Videos can be played in the record view. | requirements document §8.3, §3.1(5) | built | tests/api/test_run_files.py |
| R-041 | Videos/runs can be deleted from the app, with a confirm step. | requirements document §8.3, §3.1(5) | built | tests/api/test_runs.py; tests/api/test_clear_runs.py |
| R-042 | Clicking a video opens a second pseudo-tab showing everything known about it (status, cost by meter, steps, files, provider/model choices, rules/skills, replay). | requirements document §8.3 | planned | — |
| R-043 | The record view shows the video status and cost broken down by meter. | requirements document §8.3 | built | tests/api/test_runs.py; tests/core/test_cost_recording.py |
| R-044 | The record view shows the sequence of steps and whether each reused a previous (cached) result. | requirements document §8.3 | built | tests/core/test_records.py; tests/api/test_run_events.py |
| R-045 | The record view shows how long each step took. | requirements document §8.3 | planned | — |
| R-046 | The record view shows the exact rule and skill files in force for each agent, including their contents. | requirements document §8.3, §10 | planned | — |
| R-047 | The record view shows the provider and model choices made, with the alternatives considered. | requirements document §8.3 | planned | — |
| R-048 | The record view lists every intermediate file produced. | requirements document §8.3 | built | tests/api/test_run_files_listing.py |
| R-049 | A replay view reconstructs the run from its recorded timeline. | requirements document §8.3 | built | tests/api/test_run_events.py |
| R-050 | A live event feed shows run events (stage, log, cost, progress, heartbeat, step, result). | requirements document §9.2 | built | tests/api/test_run_events.py |
| R-051 | The Schedule tab lists scheduled entries, each pairing a workflow with saved settings, days of week, and time of day. | requirements document §8.4; mockup screen "Schedule" | built | tests/api/test_schedules_api.py; tests/core/test_schedules.py |
| R-052 | Schedule entries can be created, edited, and deleted. | requirements document §8.4 | built | tests/api/test_schedules_api.py |
| R-053 | A scheduled slot is skipped silently if the previous run of that workflow is still going. | requirements document §8.4, §9.1 | built | tests/core/test_scheduler.py |
| R-054 | A scheduled slot is skipped silently if the budget is insufficient. | requirements document §8.4 | built | tests/core/test_scheduler.py; tests/integration/test_budget_gate.py |
| R-055 | Each schedule entry has a switch determining whether approval gates pause or pass automatically. | requirements document §8.4, §9.6a | built | tests/api/test_schedules_api.py; tests/core/test_scheduler_runner.py |
| R-056 | The scheduler is opt-in (enabled by SFVF_ENABLE_SCHEDULER) and runs entries unattended. | requirements document §3.1(6), §8.4 | built | tests/api/test_scheduler_lifespan.py; tests/core/test_scheduler_runner.py |
| R-057 | The Learning tab lists every workflow with the number of quality labels accumulated since its last learning run. | requirements document §8.5, §11.2; mockup screen "Learning" | built | tests/api/test_learning_api.py |
| R-058 | Starting a learning run proposes bounded changes to that workflow's own rule and skill files only; global files are never touched. | requirements document §8.5, §11.2 | built | tests/api/test_learning_run_api.py; tests/core/test_learning_engine.py |
| R-059 | Proposed changes are always reviewed before being applied (accept/reject). | requirements document §8.5, §11.2 | built | tests/api/test_learning_api.py; tests/core/test_learning_accept.py |
| R-060 | On accept, the file's version is incremented and the previous version is archived rather than overwritten. | requirements document §8.5, §10, §11.2 | built | tests/core/test_learning_accept.py |
| R-061 | Learning runs are budgeted separately from Generation Requests. | requirements document §7.1, §11.2 | built | tests/integration/test_learning_completion.py |
| R-062 | Instruction files can be viewed and hand-edited from the Learning tab. | requirements document §8.5, §10 | built | tests/api/test_learning_edit_api.py |
| R-063 | The Statistics tab shows spend over longer periods, each meter displayed separately under its provider. | requirements document §8.6; mockup screen "Statistics" | built | tests/api/test_statistics_api.py; tests/core/test_statistics.py |
| R-064 | Real-currency providers are grouped together; credit providers are never combined with one another. | requirements document §7.1, §8.6 | built | tests/core/test_statistics.py |
| R-065 | The forecast is shown on the card and in the Statistics tab beside the historical estimate. | requirements document §7.4 | planned | — |
| R-066 | The Settings tab lets the user manage API keys and service connections (held in an encrypted file). | requirements document §8.7; mockup screen "Settings" | planned | — (Settings tab is a stand-in: renders "Arrives in a later stage") |
| R-067 | MCP connections authenticate through a one-time browser login; only the resulting token is stored. | requirements document §8.7, §6.6 | planned | — |
| R-068 | The Settings tab exposes global defaults: step silence limit, default concurrency (both axes), max cache size. | requirements document §8.7 | planned | — |
| R-069 | The encryption state is deliberately not shown in the interface. | requirements document §8.7 | built | tests/core/test_secrets.py |
| R-070 | API keys are kept in an encrypted store whose passphrase is requested at application start. | requirements document §8.7 | built | tests/core/test_secrets.py; tests/api/test_configured_secrets.py |
| R-071 | A run receives only the secrets its workflow declares (requires_keys); passphrase/secret values are scrubbed from the event stream. | requirements document §8.7, §10 | built | tests/api/test_secret_injection.py; tests/api/test_secret_exposure.py; tests/core/test_secret_redaction.py |
| R-072 | Disk thresholds are fixed: warn below 20 GB free, refuse new requests below 5 GB. | requirements document §8.7, §12 | planned | — |
| R-073 | Global step "give up" limit measures silence (time since last sign of life), not elapsed time; a live step resets the clock. | requirements document §8.7, §12, §9.2 | built | tests/core/test_supervisor.py |
| R-074 | Approval gates are excluded from any timeout. | requirements document §8.7, §9.6a | built | tests/core/test_supervisor.py |
| R-075 | Default video format is vertical 9:16 at 1080x1920; a workflow declares any other aspect/frame-rate/safe-zone. | requirements document §4 | built | tests/registry (schema: aspect/safe_zone) |
| R-076 | Safe zones are enforced by the chassis and provided to compositions as an importable stylesheet. | requirements document §4 | built | tests/integration/test_composition_check.py |
| R-077 | The declared per-workflow safe zone is honoured (no safe zone -> no margins). | requirements document §4 | planned | — |
| R-078 | A single mandatory finishing step applies consistent codec, frame rate, and loudness normalisation to every video. | requirements document §4 | built | tests/integration/test_finalize_composition_check.py; tests/integration/test_ssn_composite.py |
| R-079 | Automatic quality checks are calibrated per declared format (e.g. slideshow threshold). | requirements document §4, §9.6 | planned | — |
| R-080 | The cover frame defaults to the frame at one second in; workflows may override it. | requirements document §4 | planned | — |
| R-081 | By default a Generation Request produces N independent variants, produced in parallel and ranked afterwards. | requirements document §5.1 | built | tests/core/test_supervisor.py; tests/api/test_quality_api.py |
| R-082 | A workflow may declare its videos are a sequence (episodes): run one at a time in order, each reading where the previous ended. | requirements document §5.1 | planned | — |
| R-083 | A workflow may declare a maximum number of videos. | requirements document §5.1 | built | tests/registry (validate max_videos) |
| R-084 | A workflow may declare itself atomic: budget committed up front, underfunded run refused. | requirements document §5.1, §7.5 | built | tests/core/test_preflight.py; tests/core/test_estimate_prepare.py |
| R-085 | Real-currency providers share one budget line; credit providers each get their own labelled meter; none are summed. | requirements document §7.1 | built | tests/core/test_meters.py; tests/core/test_meters_registry.py |
| R-086 | A quota meter (monthly character allowance) is displayed and tracked, read from the provider, and not toppable mid-month. | requirements document §7.1 | dropped — owner 2026-09-27 | — (superseded: local Chatterbox TTS has no monthly quota; docs/INVENTORY.md Decisions) |
| R-087 | Each Generation Request carries its own budget, set before it starts, one line per active meter. | requirements document §7.2 | built | tests/integration/test_budget_status.py; tests/api/test_budget_activation.py |
| R-088 | Before each priced call, the estimated cost is reserved up front; on completion the reservation is replaced with the actual figure. | requirements document §7.2 | built | tests/integration/test_budget_release.py; tests/integration/test_agents_budget_release.py |
| R-089 | On failure, the reservation is released back to the budget. | requirements document §7.2 | built | tests/integration/test_budget_release.py |
| R-090 | When a budget is exhausted, an attended run pauses and asks whether to raise it or stop. | requirements document §7.2 | planned | — |
| R-091 | A scheduled run whose budget is exhausted is silently skipped rather than left waiting. | requirements document §7.2, §8.4 | built | tests/integration/test_budget_gate.py; tests/core/test_scheduler.py |
| R-092 | Cost is recorded per video (not per request), so the video count is a simple multiplier. | requirements document §7.3 | built | tests/core/test_cost_recording.py; tests/core/test_estimate.py |
| R-093 | Estimates are drawn from the last ten comparable runs, matching on cost-affecting parameters, excluding free-text params. | requirements document §7.3 | built | tests/core/test_estimate.py |
| R-094 | Failed, stopped, and dry runs are excluded from estimate history; the uncached figure feeds estimates. | requirements document §7.3 | built | tests/core/test_estimate.py; tests/core/test_cost_recording.py |
| R-095 | The estimate states its own confidence (matched with count / crude average / no data). | requirements document §7.3 | built | tests/core/test_estimate.py |
| R-096 | A workflow may forecast the remaining cost once known; the forecast is recorded next to actual spend. | requirements document §7.4 | built | tests/core/test_forecast_recording.py; tests/core/test_forecast_ordering.py |
| R-097 | An atomic run commits the whole run against the budget with a declared margin before starting. | requirements document §7.5 | built | tests/core/test_preflight.py |
| R-098 | An atomic run that exhausts budget mid-run stops cleanly (keeping completed steps) rather than pausing, and never reports partial success. | requirements document §7.5 | built | tests/core/test_supervisor.py; tests/core/test_preflight.py |
| R-099 | Each video runs as a separate OS process using that workflow's own isolated environment. | requirements document §9.1 | built | tests/core/test_proc.py; tests/core/test_supervisor.py |
| R-100 | Dependencies install themselves when a workflow's dependency fingerprint changes, showing a brief preparing state. | requirements document §9.1 | built | tests/core/test_env.py |
| R-101 | A workflow needing an uninstalled Python version is marked blocked with an instruction to install it. | requirements document §9.1 | built | tests/core/test_env.py |
| R-102 | Workflows report progress as position/total/description; SFVF imposes no fixed stage set. | requirements document §9.2 | built | tests/api/test_run_events.py |
| R-103 | The progress total may change mid-run and the display accommodates it. | requirements document §9.2 | built | tests/api/test_run_events.py |
| R-104 | A second progress line reports how many parallel units within one video have finished. | requirements document §9.2 | built | tests/api/test_run_events.py |
| R-105 | A failing step is retried up to the per-request limit (default 3). | requirements document §9.3 | planned | — |
| R-106 | When retries are exhausted, a pop-up offers the workflow's declared recovery options (choose one / retry N / abort). | requirements document §9.3 | planned | — |
| R-107 | A failed video does not stop the other videos in its request; successes are kept, failures discarded. | requirements document §9.3 | built | tests/core/test_supervisor.py |
| R-108 | There is deliberately no button to regenerate an individual video. | requirements document §9.3 | built | (by omission — no per-video regenerate control in the frontend) |
| R-109 | For a sequence workflow, a failure cancels the episodes after it. | requirements document §9.3 | planned | — |
| R-110 | Stopping is graceful: the current step finishes, its result is saved, then the process exits. | requirements document §9.4 | built | tests/core/test_scheduler_stop.py; tests/api/test_runs.py |
| R-111 | A second stop press terminates immediately, losing everything after the last completed step. | requirements document §9.4 | built | tests/core/test_scheduler_stop.py; tests/api/test_runs.py |
| R-112 | Completed steps return their saved results instantly on re-run (checkpoint/cache reuse). | requirements document §9.5, glossary "Checkpoint/Cache" | built | tests/sdk (step cache); tests/core/test_supervisor_cache_evict.py |
| R-113 | Restarting a stopped Generation Request re-enters the same run folders to resume it. | requirements document §9.5 | planned | — |
| R-114 | Changing a workflow's version invalidates its remembered (cached) results. | requirements document §9.5 | built | tests/sdk (cache key includes workflow version) |
| R-115 | Changing a workflow's version does not touch the library (library is not version-scoped). | requirements document §9.5, §10a | built | tests/core/test_supervisor_library.py |
| R-116 | Before a video is presented complete, SFVF runs deterministic self-review: file valid/playable with expected duration and resolution. | requirements document §9.6 | built | tests/core/test_self_review_recording.py; tests/integration/test_finalize_composition_check.py |
| R-117 | Self-review samples frames for black/broken frames. | requirements document §9.6 | built | tests/core/test_self_review_recording.py |
| R-118 | Self-review checks audio is neither silent nor clipping. | requirements document §9.6 | built | tests/core/test_self_review_recording.py |
| R-119 | Self-review checks captions are present when the workflow said there would be captions. | requirements document §9.6 | built | tests/core/test_self_review_recording.py |
| R-120 | Self-review checks the video is not effectively a slideshow when motion was expected. | requirements document §9.6 | built | tests/core/test_self_review_recording.py |
| R-121 | For composed pages, self-review checks nothing is off-frame or under the safe zone, no mid-word clipping, and fonts loaded. | requirements document §9.6 | built | tests/integration/test_composition_check.py; tests/integration/test_finalize_composition_check.py |
| R-122 | A video that fails self-review is marked failed rather than presented as finished. | requirements document §9.6 | deferred — owner 2026-09-24 | — (owner scoped self-review as RECORD-ONLY; hard-gating H32/H33 deferred — docs/INVENTORY.md Deferred) |
| R-123 | A workflow may pause at an approval gate before an expensive stage. | requirements document §9.6a | built | tests/api/test_gate_api.py; tests/integration/test_ssn_gate.py |
| R-124 | A gate may be a plain approve/reject, a choice among named options, or a selection over a set of items. | requirements document §9.6a | built | tests/api/test_gate_api.py |
| R-125 | Anything a gate sends back to be redone is actually re-executed (the rejection is part of the new step's identity, defeating the cache). | requirements document §9.6a | built | tests/api/test_gate_api.py |
| R-126 | A rejection note is passed to the regeneration and kept in the video's record. | requirements document §9.6a | built | tests/api/test_gate_api.py |
| R-127 | A scheduled/unattended run passes gates automatically; a gate that can do more than approve must declare its automatic answer. | requirements document §9.6a, §8.4 | built | tests/core/test_scheduler_runner.py; tests/api/test_gate_api.py |
| R-128 | Rules (always-loaded) and skills (on-demand) target agents via frontmatter, and exist both globally and per-workflow. | requirements document §10 | built | tests/core/test_supervisor_instructions.py |
| R-129 | Global and workflow-specific instructions are combined, not overridden. | requirements document §10 | built | tests/core/test_supervisor_instructions.py |
| R-130 | Instructions are frozen per run: applicable rule/skill files are copied into the run folder with content hashes and versions, grouped by agent. | requirements document §10 | built | tests/core/test_supervisor_instructions.py |
| R-131 | The library holds reusable assets that outlive runs (durable, named, described). | requirements document §10a; docs/INVENTORY.md (Library subsystem) | built | tests/api/test_library_api.py; tests/core/test_supervisor_library.py |
| R-132 | A Library tab lets the user view assets and edit their descriptors/access. | docs/INVENTORY.md (Library tab, Stage A #170) | built | tests/api/test_library_mutations_api.py |
| R-133 | Each asset carries a descriptor: structured attributes, a written description, and known defects. | requirements document §10a.1 | built | tests/api/test_library_mutations_api.py; tests/core/test_supervisor_library.py |
| R-134 | An asset is looked at once (described from the artefact) when it enters the library; later selection is by reading attributes/text. | requirements document §10a.1 | built | tests/core/test_supervisor_library.py |
| R-135 | Assets are identified by content hash, not by name; a name can be repointed. | requirements document §10a.2 | built | tests/core/test_supervisor_library.py |
| R-136 | Nothing is overwritten or auto-deleted; a redesign is a new asset recording what it supersedes; manual "remove" only deactivates. | requirements document §10a.2; docs/INVENTORY.md (Decisions) | built | tests/api/test_library_mutations_api.py |
| R-137 | Manual deletion refuses to destroy anything a past run refers to. | requirements document §10a.2 | built | tests/api/test_library_mutations_api.py |
| R-138 | The library also holds small structured persistent state (e.g. where a series left off). | requirements document §10a.3 | built | tests/integration/test_ssn_prepare.py (used-subjects value asset); tests/core/test_supervisor_library.py |
| R-139 | A library belongs to a body of work: a workflow names the collection it uses, defaulting to itself; collections are shared, not copied. | requirements document §10a.4 | built | tests/core/test_supervisor_library.py; tests/core/test_supervisor_library_owner_pool.py |
| R-140 | Per-asset access grants control which workflow(s) may use each asset. | requirements document §10a.4; docs/INVENTORY.md (per-asset access grants) | built | tests/api/test_library_api.py |
| R-141 | Asset attribute names must be declared in advance; undeclared names/values are rejected and first appearances reported (no auto-merge). | requirements document §12, §10a.1 | built | tests/core/test_supervisor_library_hardening.py |
| R-142 | Cache eviction differs by source: paid generation is never auto-evicted; renders/research evicted oldest-first past the size limit; the library is never evicted. | requirements document §12 | built | tests/core/test_supervisor_cache_evict.py; tests/core/test_cache_config.py |
| R-143 | Each finished video gets free-text answers to the workflow's declared quality factors; there are no numeric ratings anywhere. | requirements document §11.1 | built | tests/api/test_quality_api.py |
| R-144 | Per factor, the videos of a request are ranked against one another; each video is separately marked accepted or rejected. | requirements document §11.1 | built | tests/api/test_quality_api.py |
| R-145 | All quality data is stored inside the video's own record. | requirements document §11.1 | built | tests/api/test_quality_api.py; tests/core/test_records.py |
| R-146 | Criteria files live in the workflow folder, read by the learning process (not by the producing agents). | requirements document §11.3 | built | tests/core/test_learning_engine.py |
| R-147 | One example workflow ships and produces a video end-to-end in dry-run (research -> script -> gate -> speech -> visual bed -> composite -> mix -> finalize). | requirements document §3.1(9), §13 | built | tests/integration/test_ssn_workflow_dry_run.py; tests/integration/test_ssn_*.py |
| R-148 | The example workflow produces a genuinely publishable video with real spend, verified end-to-end. | requirements document §3.1(9) | planned | — (E1 live smoke run, owner-run; run sheet ready in Documents/) |
| R-149 | Audio mixing combines narration with a ducked music bed and offset sound effects into one track. | docs/INVENTORY.md (Audio mixing, Stage B) | built | tests/integration/test_ssn_composite.py |
| R-150 | Web image sourcing finds/fetches public-domain commons or paid web images, VLM relevance-checked and cached per URL. | docs/DESIGN-web-image-sourcing.md; docs/INVENTORY.md (Web image sourcing) | built | tests/integration/test_media_web_source.py; tests/core/test_web_tiers.py |
| R-151 | AI still-image and short-clip generation exists behind a provider adapter, with price() exposing pre-reserve cost for the estimate. | requirements document §6.1, §6.5; docs/INVENTORY.md (Image/video generation) | built | tests/sdk/test_media_price.py |
| R-152 | Still-image generation is behind an adapter; a workflow requiring it cannot start when unavailable. | requirements document §6.5 | built | tests/api/test_admission_model_config.py |
| R-153 | Video generation via Higgsfield (OAuth MCP, credits meter). | requirements document §6.1, §7.1 | dropped — owner 2026-09-27 | — (superseded by BytePlus Seedance + direct APIs/aggregator; docs/INVENTORY.md Decisions) |
| R-154 | Speech via ElevenLabs with character-level timings grouped into word timings for captions. | requirements document §6.1 | dropped — owner 2026-09-27 | — (superseded by local Chatterbox TTS + WhisperX; the caption capability exists via the local path) |
| R-155 | SFVF does not create voices; a voice is a bundled preset or a user-provided reference clip, referenced by identifier. | requirements document §6.6, §3.2 | built | tests/api/test_library_voices.py (non-goal honoured via bundled `preset:` ids + library voice assets cloned per call; no provider voice is created — the "created in the provider" mechanism is superseded like R-154) |
| R-156 | A `sfvf` launch command starts the app and serves the SPA and API as one process. | requirements document §3.1; docs/DELIVERY.md | built | tests/core/test_serve.py; tests/core/test_no_console_window.py |
| R-157 | A per-user Windows installer installs, upgrades in place (keeping data), and uninstalls. | docs/DELIVERY.md; docs/INVENTORY.md (Windows installer) | built | scripts/install-check.ps1 |
| R-158 | Generation Requests are refused/warned based on disk space (5 GB refuse / 20 GB warn) as a hard chassis rule. | requirements document §12, §8.7 | planned | — |
| R-159 | Planned workflow: a generation-based workflow (clips chained by first/last frame, captions, assembly). | requirements document §13 | planned | — |
| R-160 | Planned workflow: animation-to-realism (reference video input, shot-boundary detection, VLM shot descriptions, shared prepare phase). | requirements document §13 | planned | — |
| R-161 | Planned workflow: serial character drama (sequential episodes, library-carried story state and character sheets, atomic budgeting, gates). | requirements document §13 | planned | — |
| R-162 | Planned workflow: reference-driven (analyse an existing short's pacing/hook/structure, produce differentiated concepts). | requirements document §13 | planned | — |
| R-163 | Publishing/uploading is deliberately excluded; SFVF only produces files. | requirements document §3.2 | built | (by omission — no upload path exists) |
| R-164 | A learning run that errors reverts entirely to its pre-run state (no files modified) and shows a red outline with a pop-up; errors the program can handle are silent. | requirements document §8.5 | planned | — (no revert path in app/learning) |
| R-165 | Learning cards use the same outline colours as the Main tab: yellow while a learning run is in progress, green while it awaits review, cleared once the user accepts or rejects. | requirements document §8.5 | planned | — (LearningView tracks running/ready/error as text, draws no outline) |
