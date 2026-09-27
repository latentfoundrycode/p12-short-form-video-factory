# Inventory — SFVF (Short-Form Video Factory)
Reflected through: 2026-09-21 — agents.vision: real-mode LLM image attachments
Updated: 2026-09-27

## Features
| Feature | What it does | Where | Tests | Since |
|---|---|---|---|---|
| Workflow SDK | The library every workflow calls: agents (LLM/research/vision), media (image/video/speech/graphics/web/edit/finalize), and the run context | sdk/sfvf | tests/sdk | Stage A |
| Cached step boundary | Content-addressed step cache; ctx.step/ctx.map so repeated or parallel work is reused, not re-paid | sdk/sfvf/context | tests/sdk | SDK-1..3 |
| Encrypted secret store + CLI | Keeps API keys encrypted behind a passphrase; owner sets them with `python -m app.core.secrets set <NAME>` | app/core/secrets.py | tests | S1 |
| Least-privilege secret injection | A run receives only the secrets its workflow declares in requires_keys; passphrase stripped from subprocesses; secrets scrubbed from the event stream | app/core | tests | S2a-c |
| Budget circuit-breaker | Caps spend per provider, per day, and per video; reserves before a paid call and releases on failure; reconciles after-the-fact ceiling breaches | app/core/budget, sdk/sfvf | tests | T2a/T2b/Stage B/H19b |
| Local narration + voices | Speaks clean prose with Chatterbox TTS + WhisperX word alignment; selectable bundled or owner-cloned voices, per-call cloning, gentle denoise | sdk/sfvf/media/speech | tests | Speech-1..3/Stage B |
| Graphics render | Renders composed video frames through the HyperFrames node toolchain in one pass | sdk/sfvf/media/graphics | tests | B-1a/b |
| Audio mixing | media.edit.mix combines narration with a ducked music bed and offset sound effects into one track | sdk/sfvf/media/edit | tests | Stage B |
| Web image sourcing | Finds and fetches public-domain commons images (Openverse, keyless) or paid web images (SerpApi), VLM relevance-checked, cached per URL | sdk/sfvf/media/web | tests | web inc1-6 (#147) |
| Image/video generation + price | Generates AI stills (Gemini) and short clips (Seedance); price() exposes a call's pre-reserve cost for the estimate | sdk/sfvf/media/image.py, video.py | tests/sdk/test_media_price.py | Stage D |
| Finalize | Enforces the house short-form format and runs the content review as the mandatory last step | sdk/sfvf/media/finalize | tests | A-6 |
| Library subsystem | An asset library that outlives runs, with per-asset access grants and a Library tab; "remove" deactivates, never erases | app + frontend | tests | Stage A (#170) |
| Sensational Science News workflow | Researches the curated allowlist, picks a captivating non-repeating subject, writes a hook-first lay script, gates on cost, then assembles narrated 60-90s vertical video with sourced/generated visuals and Ken-Burns motion | workflows/sensational-science-news | tests/integration/test_ssn_* | Stage C/D (#172-174) |
| Windows installer + lifecycle | Per-user double-click installer that installs, upgrades in place (keeps data), and uninstalls; install-check verifies the lifecycle | installer + scripts | scripts/install-check.ps1 | PKG-3/4 (#167) |
| sfvf launch CLI + reference | `sfvf` command starts the app and serves the SPA; a command reference is generated | app | tests | PKG-1 (#165) |
| Continuous integration | GitHub Actions runs ruff, mypy, frontend lint/typecheck and tests on every PR as the required merge check | .github/workflows | n/a | CI (#699-scope) |

## Resources
| Name | Kind | Where it lives | Used by | Provided |
|---|---|---|---|---|
| SFVF_DATA_DIR | env var | user env var / installer | app.core.paths (relocatable DATA_ROOT for runs/library/secrets/ledger/schedules) | installer/owner (defaults under %LOCALAPPDATA%) |
| SFVF_SECRETS_PATH SFVF_SECRETS_PASSPHRASE | env var | user env var | app.core.secrets (encrypted store location + unlock passphrase) | owner |
| SFVF_BUDGET_CONFIG SFVF_BUDGET_STATE | env var | user env var (paths) | app.core.budget (per-meter caps TOML + persisted spend state) | owner |
| SFVF_ENABLE_SCHEDULER | env var | user env var | app scheduler (opt-in unattended runs) | owner |
| SFVF_CACHE_MAX_BYTES | env var | user env var | app.core.cache_config (cheap-cache eviction ceiling) | owner / defaults (5 GiB) |
| SFVF_DISABLE_WEB_TIERS | env var | user env var | sdk/sfvf/media/web tier gating | owner / tests |
| SFVF_HYPERFRAMES_ENTRY SFVF_HYPERFRAMES_TIMEOUT_S | env var | user env var | sdk/sfvf/media/graphics (render entrypoint + hard timeout) | owner / defaults |
| PUPPETEER_CACHE_DIR | env var | process env | frontend/installer Chromium download cache for the render toolchain | installer |
| SFVF_MARKER_KEEP | test-only env var | tests/api/test_secret_injection.py | secret-injection test (asserts a declared marker survives injection) | n/a |
| OPENROUTER_API_KEY | secret | the app's encrypted store | agents.llm/research/vision (OpenRouter) | owner (CLI set) |
| OPENAI_API_KEY | secret | the app's encrypted store | OpenAI provider | owner (CLI set) |
| GOOGLE_SA_JSON | secret | the app's encrypted store | Google image generation (Gemini/Vertex) | owner (CLI set) |
| BYTEPLUS_ARK_API_KEY | secret | the app's encrypted store | BytePlus Seedance video generation | owner (CLI set) |
| BFL_API_KEY | secret | the app's encrypted store | Black Forest Labs provider | owner (CLI set) |
| MINIMAX_API_KEY | secret | the app's encrypted store | MiniMax provider | owner (CLI set) |
| KLING_ACCESS_KEY KLING_SECRET_KEY | secret | the app's encrypted store | Kling provider (owner-deferred, no keys) | owner (not yet provided) |
| SERPAPI_API_KEY | secret | the app's encrypted store | media.web paid web-image tier (SerpApi) | owner (CLI set) |
| Node.js + npm | tool | developer machine / installer | frontend build, HyperFrames render | dev environment |
| ffmpeg | tool | developer machine / installer | media.edit.mix and finalize | dev environment |

## Decisions
| Decision | Reason | Settled | Revisit only if |
|---|---|---|---|
| The multi-provider media layer belongs to SFVF core, not to each workflow | Model/provider choice is a chassis capability; workflows just call it | 2026-09 owner | a workflow needs a provider the core cannot host |
| Prefer direct provider APIs; use an aggregator only for genuine gaps (e.g. Seedance) | Direct APIs are cheaper and more controllable | 2026-09 supervisor | a direct API becomes unavailable or an aggregator is materially cheaper |
| "Remove" means deactivate/hide from selection, never erase | Assets are content-addressed and keep their history | Stage A owner | the owner asks for true deletion |
| Native review roster (builder composer-2.5, Review A opus, Review B grok) with cross-family decorrelation | Three distinct families catch what one family misses; Grok caught real blockers the opus pair approved | 2026-09 supervisor | the full profile's other-models pool returns (2026-10-16) |
| SSN is entertainment-first, no on-screen source credit; sources go in the video description | Owner's stated priority: captivating over dry-factual | Stage C owner | the owner reprioritizes accuracy/attribution |
| SSN research is post-filtered to a 17-site curated allowlist; subjects grounded, non-repeating | Trust and safety: an off-pool or injected subject can never be returned | Stage C owner+supervisor | the owner changes the trusted-site list |
| Approval gate and per-video budget are run settings, not baked into the workflow | The owner sets risk per run (Manual vs Autonomous, budget cap) | Stage B owner | a workflow needs a fixed policy |
| Secrets live in an encrypted store unlocked by a passphrase; the app injects only requires_keys secrets | Least privilege; a workflow sees only what it declares | S-series supervisor | a broader injection model is needed |
| Project state is two bounded files: PROJECT_STATUS.md (<=120 lines) + INVENTORY.md | A status file grown into a log is read in slices and the needed fact is skipped (bridge rule 41) | 2026-09-27 supervisor | the bridge changes the state-file contract |

## Deferred
| Item | Why deferred | Since | Owner decision needed |
|---|---|---|---|
| Settings tab full build (§8.7: API keys via GUI, MCP, global defaults) | Shipped as a placeholder in v1.0.0 with no recorded deferral; owner has chosen to build it FULLY | v1.0.0 / surfaced 2026-09-27 | yes — approve scope to start (owner already chose "full") |
| E1 live smoke run (real spend ~$6-8/video) | Needs the owner's real API keys and real money; run sheet ready in Documents/ | Stage E | yes — owner runs it |
| Remove smoke_openrouter / smoke_higgsfield / smoke_provider / explainer workflows | Stage-E cleanup, batched with the finalization pass | Stage E | no |
| VERSION bump to 1.1.0 + user manual | End-of-cycle finalization after features land | Stage E | no |
| Main workflow card §8.1 (avg cost, running-stage, archived state, outline colours) | Audit gap F2; part of the paused audit-driven plan | audit 2026-09-27 | yes — scope approval |
| Run pop-up/cost §8.2/§7.3, reliability §9.3/§7.2/§7.4/§12, video list §8.3 | Audit gaps F3-F5; part of the paused audit-driven plan | audit 2026-09-27 | yes — scope approval |
| Self-review hard-gating (H32/H33) | Owner scoped self-review as record-only for now | Stage C | yes — owner (explicitly deferred) |
| completion.py budget reserve/release latent bugs (same class as the inc0 agents.llm fix) | Follow-up hardening, not on the critical path | inc0 | no |
| Kling provider (KLING_ACCESS_KEY / KLING_SECRET_KEY) | Owner has not provided keys | Stage P | yes — owner provides keys |
| CHANGES.md ordering: the change-cycle entries were appended at the file's bottom rather than newest-first | Cosmetic log-ordering cleanup; does not affect behaviour | 2026-09-27 | no |
