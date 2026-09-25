# Design — Change cycle: "Sensational Science News" (2026-09-26)

Change cycle on the finished SFVF project (v1.0.0 -> target v1.1.0, a minor bump: new feature + first real content workflow, no existing behaviour removed except deleting three test workflows). Per-change design doc (cf. `docs/DESIGN-web-image-sourcing.md`); unchanged chassis design in `docs/SFVF_Architecture.md` and `docs/SFVF_Workflow_SDK.md` is referenced, not rewritten. Security level: ASVS L2 for the new HTTP surfaces. Rev 3: folds in the plan-critic review (budget mechanism, prepare/run split, gate placement, budget-config prerequisite, mixer toolchain, slideshow risk, upload streaming) AND the two owner changes at the design gate: per-asset ACCESS CONTROL (grant to all or specific workflows) and SELECTABLE VOICES (in scope now).

## 1. Purpose and scope

Deliver SFVF's first real content workflow, "Sensational Science News": research a curated set of science-news sites, select an entertainment-first subject, write an attention-first script (a curiosity/fear hook, then an accurate-but-lay-accessible body unfolding into hypotheticals about implications), and produce a 60-90 s vertical video with an AI voiceover in an owner-chosen voice, center-screen captions synced to the voice, a visual bed of web-sourced + AI-generated imagery + a few AI clips, and owner-supplied background music and SFX. Plus the reusable chassis capabilities it needs.

Three chassis parts (reusable) + the workflow + a removal:
- Part 1 — Library subsystem: an owner-facing Library tab to manage reusable assets (music, SFX, and voice reference clips), each with OWNER-CONTROLLED ACCESS (grant to all workflows or a chosen set of specific ones), add / edit / deactivate.
- Part 2 — Workflow enablers (chassis): new run settings (approval mode, per-video budget, narrator voice; video count already exists), a per-video aggregate spend ceiling, an audio mixer (`media.edit.mix`), SELECTABLE VOICES (wire the local TTS to honour a chosen voice), and a per-video `description` output field.
- Part 3 — the `sensational-science-news` workflow, by repurposing `explainer`.
- Removal — delete the `smoke_provider`, `smoke_openrouter`, `smoke_higgsfield` test workflows.

## 2. Non-goals

No auto-publishing (SFVF produces the file + a description; posting is manual). No on-screen source citation (sources go in the per-video description). No scheduling logic in the workflow (SFVF's scheduler owns it). The Library tab manages assets (audio + voice clips) but is not a media editor or waveform player. No CLOUD/paid TTS provider — voices are the LOCAL Chatterbox engine conditioned on reference clips (§6.5). No music/SFX PROVIDER integration (the doc's `media.music`/Epidemic Sound stub stays unbuilt; music and SFX come only from the owner's library).

## 3. The workflow — pipeline design

Reuses the `explainer` spine and extends it. Each video is a DISTINCT subject, not a variant; nearly all spend and the approval gate live in per-video `run()`, so the per-video ceiling actually covers them.

- `prepare()` (once per request, cheap TEXT only): fetch a shared POOL of candidate articles via `agents.research` + light LLM scoring. No paid media here, so prepare spend is a few cents of `openrouter`, bounded by that meter's `per_run` cap (§12). Returns the pool as `ctx.shared`.
- `run()` (per video): select the next distinct, unused subject (§3.2) -> script (§3.3) -> approval gate (§6.2) -> paid media (§3.5) -> voiceover + center captions (§3.4) -> music/SFX + mix (§3.6) -> assemble + finalize + description (§3.7). Gate and paid media at a numeric `video_index` -> the verified gate-API path; every paid call per-video-attributed.

Paid calls wrapped in `ctx.step(..., paid=True)` (resume never re-pays). `video_semantics` set to the schema value meaning independent videos (exact enum taken from `app/registry/schema.py` at build; `explainer`'s `variants` is wrong for distinct subjects). Used-subjects carried within a run via `ctx.previous` and across runs in the library (§3.2).

### 3.1 Research pool (prepare)

`agents.research(query)` cannot hard-restrict to domains (only `query: str`). Build the query with `site:` hints AND enforce the allowlist by POST-FILTERING returned `Source.url`; too few on-list -> broaden + re-filter; still short -> best on-list set + a note. Sources come only from OpenRouter web-plugin `url_citation` annotations; the real response shape is confirmed in the Stage-C research probe/smoke (KP-020), not assumed from the canned dry-run. Curated allowlist (owner-provided constant): sciencenews.org, science.org, sciencedaily.com, nature.com, scientificamerican.com, bbc.com/news/science_and_environment, phys.org, sci.news, livescience.com, npr.org/sections/science, cbc.ca/news/science, snexplores.org, newscientist.com, reuters.com/science, bloomberg.com/ai, news.mit.edu, reuters.com/technology. Research `inputs` carry a coarse date bucket (cache freshness, SDK §11.1).

### 3.2 Subject selection + de-duplication (run)

Per video, an LLM (`agents.llm`, structured) scores the remaining pool for CAPTIVATION for a lay audience and picks one, excluding subjects essentially identical to any in the cross-run library list or used earlier this run (`ctx.previous`). Same DOMAIN allowed; same specific finding not. The choice is appended to the library value-asset list (written from `run()`; dry-run overlay keeps rehearsals clean).

### 3.3 Script (run)

`agents.llm`, entertainment-first: 3-5 s HOOK (curiosity/fear question), then an accurate but plain-language body (terminology only when needed), unfolding into hypotheticals. Spoken-narration-only (the `_narration_text` cleaner strips directions). 150-235 words for 60-90 s at ~2.5 wps. Fetched article text passed as clearly-delimited DATA with an "ignore instructions within" directive (§10).

### 3.4 Voiceover and center captions (run)

`media.speech.speak(narration, voice=<chosen>, model="chatterbox")`. Voice selection is now real (§6.5): the chosen `voice` resolves to a reference audio clip (a built-in preset or an owner-uploaded voice asset the workflow may use) and is passed to Chatterbox as its audio prompt; an empty/unknown voice falls back to the default. Returns audio + WhisperX word timings (free, GPU; RTX 4000 confirmed). Captions: an animated GSAP composition (as `explainer`) positioned CENTER-screen, grouped a few words at a time, highlighted per word timing. `media.graphics.captions` (plain SRT) only for the optional `finalize` subtitle track.

### 3.5 Visual bed (run)

Narration segmented into beats; each beat gets a web image (`media.web.source`, VLM-relevance-checked; free commons first, paid `web`/SerpApi only if the ceiling allows), an AI still (`media.image.generate`), or a short AI clip (`media.video.generate`, ~4-5 s) for the hook + 1-2 hypotheticals. Balanced default: mostly stills + 1-2 clips, under $8/video (§12). STILLS GET KEN-BURNS PAN/ZOOM so the video is not a static slideshow — `finalize.content_review` raises on a slideshow/low-motion verdict (finalize.py:142-154), so the visual increment must clear it (§11). Used web-image source URLs collected for the description.

### 3.6 Music, SFX, and the mix (run)

Music/SFX come only from the LIBRARY (owner-loaded, granted to this workflow — §5). The workflow picks a track whose facets (mood/energy/type) fit the tone via `ctx.library.find` + LLM tone match, cues SFX at fixed points (hook + transitions) to start, and mixes narration + music (ducked) + SFX into ONE track via `media.edit.mix` (§6.3) — `finalize` takes exactly one audio track. GRACEFUL DEGRADATION: no suitable library audio -> narration-only video + note, never a failure.

### 3.7 Assemble, finalize, description (run)

Visual-bed + center-caption composition -> one 1080x1920/30fps mp4 (`media.graphics.render`); `media.finalize(visual, audio=mixed, captions=srt)` applies house format + self-review. Returns `Result(video, caption, description=<source URLs>)`.

## 4. Key technical risk — compositing a mixed image/clip bed with captions

`media.graphics.render` uses the HyperFrames headless-Chrome toolchain; whether it captures PLAYING `<video>` clips frame-accurately alongside the GSAP caption timeline is UNVERIFIED. Per rule 15 / KP-008, Stage C OPENS with a throwaway probe. Approach (a): all-in-HTML. Fallback (b): ffmpeg/kinocut visual bed + overlay a transparent caption composition. The probe picks (a)/(b) before the visual increment; recorded, not escalated.

## 5. Part 1 — Library subsystem, with per-asset access control (chassis)

The content-addressed `LibraryStore` exists; today it is reachable only inside a running workflow, and sharing is by workflows declaring the same namespace in `workflow.toml`. The owner wants finer, OWNER-CONTROLLED access: each asset grantable to ALL workflows or a chosen SET of specific ones. Design:

- Two asset origins remain distinct: (i) WORKFLOW-GENERATED assets stay in the workflow's own namespace (`library/<workflow-id>`) — dedup lists, sourced images, etc., unchanged. (ii) OWNER-UPLOADED assets (music, SFX, voice clips) live in a single owner pool (`library/_owner`) and each carries an ACCESS GRANT.
- Access grant: a mutable per-asset record, `{"all": true}` OR `{"workflows": ["id1","id2",...]}`, stored in a mutable `grants.json` in the owner pool (shape like `aliases.json`; editable without a new asset id, since grants are metadata not content). The Library tab sets it: "All workflows" or a multi-select of specific workflow ids (from the registry).
- Read view: a workflow W's `ctx.library` returns W's own-namespace assets UNION the owner-pool assets whose grant is `all` or includes W. This is a new merge in the `Library` facade (`context.py`): it reads the workflow's namespace root and the owner-pool root, applies the grant filter for W's id (available from the manifest/context), and merges results deterministically. Per SDK rule 5.3a, `find()` is called OUTSIDE steps and resolves to asset ids that are then declared inside steps — unchanged; the grant filter runs at `find()` time.
- App-side access: add `library_dir` param + `application.state.library_dir` in `create_app` (mirroring `runs_dir`, for temp-library test isolation — plan-critic C14). New `app/api/library.py` router (prefix `/api`) in `app/main.py`.
- Owner-pool facet vocabulary is FIXED by the chassis (not per-workflow-declared, which sidesteps the shared-namespace facet-reconciliation problem entirely): `type` in {music, sfx, voice}, plus open `mood`, `energy`. The tab reads/writes these.
- Endpoints: `GET /api/library/assets` (owner pool, all statuses, with grant + facets); `GET /api/library/workflows` (workflow ids+labels for the grant picker, from `RegistryHolder.snapshot`); `POST /api/library/assets` (multipart upload; adds `python-multipart`, dependency-gated, lockfile same increment — KP-018; enforce max-bytes DURING streaming, abort on breach — plan-critic A9; validate media type — audio: mp3/wav/m4a/ogg, voice: same; then `LibraryStore.put(...)` content-addressed by hash; client filename never a path); `PUT /api/library/assets/{id}` (edit facets/caveats via `annotate` + edit grant); `POST /api/library/assets/{id}/grant` (set access); `POST .../deactivate` + `/reactivate`.
- Deactivate ("remove" = hide, not erase): NEW `LibraryStore.deactivate(id)`/`reactivate(id)` flip a new `inactive` status (distinct from `superseded`); `find(status=...)` honours it; nothing deleted from disk.
- Frontend: a `library` tab (`tabs.ts` + `Shell.tsx` `TabIcon` + `App.tsx` ladder) and `LibraryView.tsx` (Learning-tab pattern: list left, detail+edit right); the detail pane edits facets and the ACCESS grant (All / multi-select workflows); typed helpers in `api.ts`.

## 6. Part 2 — Workflow enablers (chassis)

### 6.1 Run settings (approval mode, per-video budget, voice; video count exists)

Thread new fields through `LaunchBody` (`app/api/runs.py`) -> `launch_run` -> `admit_run` (already accepts `gates_auto`) -> `run_request`/supervisor -> the run's `context.json`; add controls to `RunLaunchForm.tsx`:
- Approval mode -> the built-but-not-launch-settable `gates_auto` ("Autonomous" True / "Manual approve" False). MANUAL APPROVE IS FOREGROUND-ONLY: scheduled/unattended runs must use Autonomous or block forever at the gate (plan-critic C13); the UI warns on that combination.
- Per-video budget -> the per-video ceiling (§12), via a per-run `BudgetConfig` view.
- Narrator voice -> the voice id (§6.5); the workflow declares a default.

### 6.2 Approval gate (start of run())

`ctx.gate("approve-plan", prompt=..., payload={subject, script, prepare_cost_so_far, estimated_media_cost})` at the START of each video's `run()` (numeric `video_index`, the verified gate path — avoids the unverified prepare-phase gating, plan-critic B4). Autonomous -> `gates_auto` bypass. Reject -> `GateRejected` ends THAT video; siblings continue. Payload names the small prepare cost already incurred + the media estimate (plan-critic C15). No new gate runtime.

### 6.3 Audio mixer — `media.edit.mix`

`media/edit.py` (trim/cut) is built on `kinocut.Client` (NOT `_ffmpeg`). Build `media.edit.mix(narration, *, music=None, sfx=None, duck=True) -> path` on the same kinocut toolchain (`add_audio(mix=True)` + kinocut ducking/`audio_bed`), one m4a for `finalize`. VERIFY-FIRST (KP-008): prior probing found kinocut's `audio_compose` hung, so the increment OPENS with a probe of the exact duck + offset-SFX path and falls back to a direct ffmpeg filtergraph (amix + sidechaincompress) if kinocut is not dependable. Its own increment, not a stub (plan-critic A5).

### 6.4 Per-video description field

Add `description: str = ""` to `Result` (`result.py`), thread through the runner result event and `VideoRecord` (`app/core/records.py`), surface read-only in the run view. Additive; existing records read "".

### 6.5 Selectable voices (chassis)

Chatterbox is a voice-cloning TTS: `ChatterboxTTS.generate(text, audio_prompt_path=<ref clip>)` conditions on a reference clip (verified `_synthesize` calls `generate(text)` today with `voice` discarded, speech.py:47-57). Wire `media.speech`:
- `_synthesize` resolves `voice` to a reference clip path and passes `audio_prompt_path` to `generate`; empty/"default"/unknown -> no prompt (default voice). The cache key already includes `voice` (speech.py:135), so different voices cache separately — no cache change.
- Voice registry = BUILT-IN PRESETS (a few bundled reference clips shipped under `assets/voices/`) + OWNER voices (library assets of `type=voice`, granted to workflows like any asset — §5). A resolver maps a voice id to a preset path or a granted voice asset's blob.
- Voice is a run setting (§6.1) and a workflow default; the Library tab manages owner voice clips (upload + name + grant), same surface as music/SFX.
- VERIFY-FIRST probe (KP-008): confirm Chatterbox `audio_prompt_path` conditioning works under our GPU/headless setup and that WhisperX alignment still holds, before relying on it; fall back to default-voice-only if it does not.

## 7. Removal of test workflows

Delete `workflows/{smoke_provider,smoke_openrouter,smoke_higgsfield}` (dirs + registry references). `explainer` is repurposed, not deleted. Any "exactly N workflows" test updated.

## 8. Data model and migration

Post-release regime: additive only. New/changed shapes, all additive: the library `inactive` status (older catalogs default active); the owner pool + `grants.json` (new files under `library/_owner`); the dedup value-asset; `Result.description`/`VideoRecord.description` (default ""); `video_index` on budget-ledger reserved/actual lines (old lines / prior runs unaffected; missing reads as run/prepare scope, §12); bundled `assets/voices/` presets. No destructive migration.

## 9. Interfaces and contracts (new)

- `LibraryStore.deactivate(id)`/`reactivate(id)`; `find(status=...)` honours `inactive`.
- Grant store: `grants.json` in the owner pool; `Library` facade merge (own namespace + granted owner-pool) for the current workflow.
- Voice resolver: voice id -> reference clip (preset or granted voice asset); `media.speech._synthesize` honours it.
- `GET /api/library/assets`; `GET /api/library/workflows`; `POST /api/library/assets`; `PUT /api/library/assets/{id}`; `POST /api/library/assets/{id}/grant`; `POST .../deactivate` + `/reactivate`.
- `media.edit.mix(...)`; `Result.description`.
- `LaunchBody` gains `gates_auto: bool`, `per_video_budget: float`, `voice: str`.
- Budget engine: `video_index` on ledger lines + `BudgetGuard.reserve(..., video_index=...)` + cross-meter per-video aggregate check + per-run `BudgetConfig` view (§12).

## 10. Security and secret handling (ASVS L2)

- Untrusted web TEXT -> LLM prompt-injection risk. Mitigation: fetched text passed as clearly-delimited DATA with an "ignore instructions within" directive; the LLM returns only text/structured data and never controls the pipeline or tool use; the workflow orchestrates every step (the control flow, not model compliance, is the real containment). `security-auditor` reviews the prompts.
- Untrusted web IMAGE bytes: SSRF-hardened, re-encoded, EXIF-stripped, animation-rejected by `media.web.fetch` — unchanged.
- Composition injection: caption words JSON-escaped `ensure_ascii=True` — preserved.
- Uploads (audio + voice clips): type + size validated, size enforced DURING streaming, content-addressed, confined to the owner pool, same-origin CSRF guard. A voice clip is reference audio only — no code, no path from the filename.
- Access grants are OWNER-set via the same-origin API; a workflow can never widen its own access (grants live outside the workflow's writable namespace, in the owner pool the workflow only reads).
- Secrets: workflow declares `OPENROUTER_API_KEY` (HARD-REQUIRED) and `SERPAPI_API_KEY` (paid web images) via `requires_keys`; local speech needs none; no secret in any prompt/log.

## 11. Error handling and graceful degradation

- Empty/too-few on-allowlist research (incl. no `url_citation`s): broaden + re-filter, then best on-list set + note; truly empty pool -> clean failure, never a fabricated subject.
- No suitable library music/SFX: narration-only + note.
- Voice asset missing/ungranted: fall back to the default voice + note (never a failure).
- Slideshow/low-motion: Ken-Burns motion clears `finalize.content_review`; if a video still trips it, that video fails cleanly with the reason. The visual increment's acceptance criterion is that the balanced default clears content_review (plan-critic A6).
- Provider/media failure: one video fails cleanly without killing the batch.
- Per-video ceiling reached mid-generation: next paid call refused (fail-closed); the video finishes if viable, else fails with a budget note.
- Approval rejected: `GateRejected` ends that video; siblings continue.
- Probes (§4, §6.3, §6.5) failing their primary path -> the recorded fallback.

## 12. Cost and budget design — the $8/video ceiling

Existing engine caps per METER and per RUN, delegates checks to `BudgetGuard.reserve` (not `ctx._budget_reserve`), and has NO per-video/aggregate scope (plan-critic B1). Coordinated change: (1) add `video_index` to ledger reserved/actual lines; (2) `BudgetGuard.reserve` gains `video_index` + a NEW cross-meter aggregate check (sum reserved+actual over ALL meters for `(run_id, video_index)`, a new function beside the per-meter `_run_sum`) refusing the call that would breach the per-video ceiling; (3) `ctx._budget_reserve` passes `ctx.video_index` + the ceiling; (4) a per-run `BudgetConfig` view carrying `per_video_budget` (today `BudgetConfig` is an app singleton) threaded from `LaunchBody` -> `context.json`. Per-meter caps still apply underneath.

TRUE BOUND (plan-critic B2): `prepare()` spend (cheap `openrouter` text, no paid media by design) is NOT per-video-attributed; it is bounded by the `openrouter` per-meter `per_run` cap. Real request max = `prepare_spend + $8 x N`, disclosed to the owner (§16).

PREREQUISITE (plan-critic B3): with `SFVF_BUDGET_CONFIG` unset or any used meter lacking a positive `estimate` + `per_run`, every paid call is refused (fail-closed) and the workflow cannot run — the §14 live smoke is then unreachable. So a Stage-C PREREQUISITE increment + owner setup: an `SFVF_BUDGET_CONFIG` TOML with positive `estimate`+`per_run` for every used meter (`openrouter`, `serpapi`, and the image/video meters used — `openai`/`google`/`bfl`/`byteplus`/`minimax`), plus `OPENROUTER_API_KEY` (hard-required) and `SERPAPI_API_KEY`. Handed over as a run sheet (§16).

## 13. Observability and verifiability (UI-bearing)

New UI: the Library tab (assets + access-grant editor + voice management) and the run-launch settings (approval, per-video budget, voice). Tier A. Library-tab inventory states: empty / sparse / dense / error (list + upload failure) + a grant-editing state. Reachability: deep-linkable view id. Baseline invariants: no undefined/NaN/[object Object]/untranslated key; `console.error` fails. Observability e2e tests drive each state through the real render path. Tier B (screenshots) at discretion.

## 14. Testing strategy

- SDK unit: `deactivate`/`reactivate` + `find` filtering; the grant-merge read view (a workflow sees `all` + its own grants, not others'); the voice resolver (id -> preset/asset; unknown -> default); `media.edit.mix` (streams/duration; ducking) on tiny fixtures; the per-video aggregate ceiling (refuses the cross-meter breach; per-meter/per-run honoured; `video_index` recorded); `Result.description` round-trip.
- App: library endpoints (list/upload/annotate/grant/deactivate; path-safety; streaming size + type validation; CSRF); run-settings plumbing (gates_auto + per_video_budget + voice reach the run); `library_dir`-injected temp library.
- Frontend: Library tab (incl. grant editor + voice upload) + run-launch settings observability tests; no `console.error`.
- Workflow: dry-run graph tests (dedup; graceful degradation with no audio/voice; description carries sources). DoD is an ATTENDED LIVE SMOKE (real spend, owner keys, real research + real Chatterbox voice) producing one real video end-to-end — the smoke verifies `research()`'s real shape and the voice-conditioning path (KP-020); a green dry-run tests only assumptions.
- Probes (their own throwaway steps): compositing (§4), kinocut mix (§6.3), Chatterbox audio-prompt (§6.5).

## 15. Delivery

`VERSION` 1.0.0 -> 1.1.0. Installer rebuilt + re-verified by `scripts/install-check.ps1` at project end (Installer verification: local); "already installed" dialog exercised once. User Manual gains a Library-tab chapter (assets, access grants, voices) and a "Sensational Science News" usage + setup (keys + budget config) section. No code-signing change. The bundled `assets/voices/` presets ship inside the installed program (part of the app payload, under `%LOCALAPPDATA%\Programs\SFVF`).

## 16. Decisions for the owner and known limitations

- VOICE (now in scope): built-in preset voices ship, and you can add your own voices in the Library tab (upload a short reference clip; the AI clones it). A verify-first probe confirms the cloning path works under your GPU before we rely on it; if it somehow does not, we fall back to the single default voice and tell you.
- SETUP BEFORE THE FIRST REAL RUN: (a) load music/SFX (and any custom voices) in the Library tab, granting them to this workflow or all; (b) `OPENROUTER_API_KEY` (hard-required) + `SERPAPI_API_KEY`; (c) a budget-limits file (without it every paid call is refused). Handed over as run sheets at the right stages.
- COST TRUTH: $8/video governs each video's media; a batch of N can cost up to ~$8xN plus a few cents of research per run. Overridable per run.
- MANUAL-APPROVE is foreground-only: scheduled runs must be Autonomous.
- SCOPE/EFFORT grew slightly with selectable voices, but voices reuse the same Library-asset + grant machinery, so the marginal cost is the TTS wiring + a probe, not a new subsystem.
- Everything else (allowlist post-filter, compositing/mix/voice probes, budget mechanics, prompt-injection defence, the grant read-path) are engineering choices recorded here.

## 17. Build approach (stages — full plan at Phase 4)

Milestones: (A) Library subsystem end-to-end — owner pool, per-asset access grants, deactivate, upload, the tab (owner can load/manage/grant music, SFX, and voice clips); (B) workflow enablers — run settings, per-video budget engine change, audio mixer (+probe), voice wiring in `media.speech` (+probe), description field; (C) the workflow — OPENING with the compositing probe + research-response probe + the budget-config/keys prerequisite, then the pipeline increments, ENDING with the attended live smoke; (D) cleanup + packaging — remove test workflows, version bump, installer re-verify, manual. Ordering: A before C (audio/voices loadable before the smoke), B before C (enablers exist), probes before dependent increments. Full list + acceptance criteria at Phase 4.

## 18. Open questions

- Compositing (a)/(b), mixer kinocut-vs-ffmpeg, and voice-cloning viability — resolved by the Stage-B/C probes, not the owner.
- SFX cueing (fixed vs LLM-chosen) — starts fixed, refined in Stage C.
- Number/character of the bundled preset voices — a small content choice, defaulted (a few distinct narrator styles), extensible by owner uploads.

## 19. Rev 4 amendments — focused plan-critic (access control + voices)

These amend the sections named; where they conflict with an earlier section, these win.

- BLOB READ PATH (B1, amends §3.6/§6.5/§9): the `Library` facade gains a grant-aware, two-root file-path accessor `ctx.library.path(name_or_id) -> Path | None` — it resolves in the workflow's own namespace first, then the owner pool (applying the grant filter for this workflow), and returns the on-disk blob path. This is the load-bearing read used to hand music/SFX to `media.edit.mix` and to resolve a voice clip; it is a first-class interface with its own unit test (a workflow can read a granted owner asset's bytes and cannot read an ungranted one). Without it, §3.6 and §6.5 have no read path.
- VOICE CONDITIONING ISOLATION (B2, amends §6.5/§14): `_synthesize` sets Chatterbox conditionals EXPLICITLY on every call — the base/default voice passes the bundled base reference (or an explicit conds reset), never "no audio_prompt" — because `_tts_model` is a process-global instance (`speech.py:50`) whose conditionals persist between calls and would otherwise leak the previous voice. The §6.5 probe and a §14 test MUST assert cross-voice isolation in one process: voice A -> default -> voice B each produce output matching its target, not the prior voice.
- OWNER-POOL WIRING (S1, amends §5/§9): add an explicit `library_owner_pool: Path` to `ContextPaths` (`context.py:68`), set by the supervisor (`supervisor.py:~282`/`~471`) to `(library_dir or LIBRARY_DIR)/_owner`, and read by `_make_library`; do not rely on implicit sibling derivation.
- CROSS-ROOT PRECEDENCE (S2, amends §5/§9): for `get`/`resolve`/`path`/`find`, the workflow's OWN namespace wins over the owner pool on any name or id collision; the owner-pool source folds into `find()` AFTER the existing dry-run-overlay/real dedup (overlay > own-namespace > owner-pool), and an owner-pool asset already present by id in a nearer source is not duplicated.
- OWNER POOL IS READ-ONLY TO WORKFLOWS (S4, amends §5/§9/§10): the owner-pool store is instantiated read-only in the facade — `put`/`annotate`/`deactivate` never route to it (writes go only to the workflow's own namespace / dry-run overlay, `context.py:315`). §10's "a workflow can never widen its own access" is corrected to "cannot widen access THROUGH THE SDK API"; at the OS level workflows are trusted plugins (SFVF's existing model), not filesystem-sandboxed.
- PRESET PATH RESOLUTION + PACKAGING (S3, amends §6.5/§15/§17): the voice resolver locates bundled presets relative to the SDK source (`Path(__file__).resolve()` walk to the install/repo root's `assets/voices/`, the same mechanism `graphics.py:202` uses for `tools/`); the SDK is installed editable in workflow venvs (`env.py:101`), so this resolves today. Packaging acceptance criterion (Stage D): `assets/voices/` is present and reachable from a workflow venv on an INSTALLED machine (force-include `assets` in the SDK wheel build if/when the SDK ships as a built wheel).
- VOICE CACHE KEY (A1, amends §6.5): the speech cache/artifact key uses the RESOLVED clip's content hash (for an owner voice, its content-addressed asset id; for a preset, the file's hash), not the voice id string — so re-pointing a voice name to a new clip does not serve stale narration.
- VOICE ID PRECEDENCE (A5, amends §6.5): a `preset:` prefix is reserved for bundled presets; an unprefixed voice id resolves to a granted owner voice asset, then falls back to a preset of that name, then to the base voice — deterministic.
- GRANTS.JSON CONCURRENCY (A2, amends §5/§11): the app writes `grants.json` atomically (`os.replace`) with a short retry on a Windows sharing violation; the run-side read is open/read/close (brief). 
- GRANT TIMING + DANGLING GRANTS (A3/A4, amends §7/§11): grant changes take effect on the NEXT run, not mid-run (ids already resolved into step inputs stand). Grants referencing a now-deleted workflow id (after §7) are ignored on read (harmless dead data); the grant picker only offers ids in the registry.

## 20. Rev 5 amendments — build-plan plan-critic (subject model, research, motion, description)

- SUBJECT SELECTION MOVES TO prepare() (amends §3/§3.2): the chassis does NOT chain videos — `ctx.previous` is always None in the real run path and `video_semantics` is consumed nowhere (validated only), and videos run CONCURRENTLY in a thread pool (so a per-video read-then-append to the dedup list would race). Therefore prepare() (which runs ONCE, before the parallel per-video workers) selects ALL N distinct subjects (N = the video-count run setting) from the pool in one pass — excluding the cross-run library list and each other — appends all N to the library list atomically, and returns them in `ctx.shared`. `run(video_index)` uses `ctx.shared["subjects"][video_index]`; it does NOT select or dedup. This is race-free and needs no `ctx.previous`. `video_semantics = "variants"` (a real enum value; the field is currently inert, so the label is cosmetic — distinctness is enforced by prepare's per-index assignment). The approval gate + script stay per-video in `run()` on the assigned subject.
- RESEARCH IS ALREADY SHIPPED (amends §3.1): `agents.research` is built and in use (by `explainer`), so its `Source` contract is known — this is NOT a new external-adapter contract capture. Only the site:-bias + allowlist-filter QUALITY is unverified, and that is a tuning concern verified at the E1 live smoke, not a Stage-C live probe (which could not run before the owner's OpenRouter key + budget config exist anyway). No Stage-C "research probe recorded" step.
- MOTION CHECK HAS A PRE-SPEND CHECKPOINT (amends §3.5/§11): `finalize.content_review` runs only on a real (non-dry) render, so the "Ken-Burns clears the slideshow/low-motion guard" guarantee is checked by a small NON-DRY mini-render test over a real Ken-Burns fixture at the visual increment (local, free), not deferred silently to the live smoke.
- DESCRIPTION VIA THE EXISTING RECORD FIELD (amends §6.4): `Result.description` round-trips into `VideoRecord.result` (a free-form dict) automatically, so the run view surfaces `result["description"]` — no new top-level `VideoRecord.description` field and no touching the `extra="forbid"` model.
