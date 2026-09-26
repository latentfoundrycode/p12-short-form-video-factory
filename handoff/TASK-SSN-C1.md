# TASK-SSN-C1 — Scaffold the Sensational Science News workflow (repurpose explainer)

Create the new workflow `workflows/sensational-science-news/` by repurposing `workflows/explainer/`. This is the SCAFFOLD: a discoverable, valid plugin whose prepare()/run() pipeline runs end-to-end in dry-run producing a real vertical `final.mp4`. The real research/subject-selection, script, and media-sourcing land in later increments (C2/C3/D); here the content is placeholder but the STRUCTURE and the `ctx.shared["subjects"]` contract are established. Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/registry/test_ssn_workflow.py` (valid manifest, fields, own requirements)
- `tests/integration/test_ssn_workflow_dry_run.py` (dry-run -> final.mp4 + complete; prepare returns subjects)

## Files to create (only under workflows/sensational-science-news/)

### workflow.toml
- `[workflow]`: `id = "sensational-science-news"`, `name = "Sensational Science News"`, `version = "1.0.0"`, `entrypoint = "main:run"`, `prepare = "main:prepare"`, `sdk = "1"`, `video_semantics = "variants"` (a real enum value; it is inert -- distinctness comes from prepare's per-index subject assignment, rev-5).
- `[output]`: `aspect = "9:16"`, `fps = 30`, `safe_zone = "tiktok"`.
- `requires_keys`: two entries -- `OPENROUTER_API_KEY` (label "OpenRouter"; the LLM steps) and `SERPAPI_API_KEY` (label "SerpApi"; paid web images used from Stage D). Local speech needs no key.
- Do NOT declare `[[params]]` for approval mode / video count / per-video budget / voice -- those are LAUNCH run-settings (LaunchBody) read from `ctx` (ctx.gates_auto / ctx.video_count / ctx.per_video_budget / ctx.voice), not workflow params. (You may add no params at all; the workflow selects subjects autonomously.)

### requirements.txt
Copy `workflows/explainer/requirements.txt` verbatim (the CUDA torch pin + chatterbox-tts + whisperx + setuptools<81 + httpx2). Issue 3: the workflow's venv is built from this file, so it must pin every heavy import the workflow uses. (Web-image deps are added in Stage D when media.web is first used.)

### main.py (repurpose explainer/main.py; NO cross-workflow imports -- copy any helper you reuse)
- `prepare(ctx) -> dict`: return `{"subjects": [...]}` with exactly `ctx.video_count` entries -- placeholder distinct subject strings for now (e.g. wrap `ctx.step(...)` around a stub list `[f"Placeholder science subject {i + 1}" for i in range(ctx.video_count)]`). This is the shape C2 will fill with real research + N-distinct-subject selection. Do NOT call the real research pipeline yet.
- `run(ctx) -> Result`: `subject = ctx.shared["subjects"][ctx.video_index - 1]` (video_index is 1-based). Then, reusing explainer's structure (copied into this file): write a placeholder narration for `subject` via `agents.llm(...)` (it stubs in dry-run), reduce it to spoken text, `media.speech.speak(narration, voice=ctx.voice, model=...)` -- use `ctx.voice` (the run-setting), NOT a param -- render the caption composition (copy explainer's `_composition_html`/caption helpers), `media.graphics.render`, `media.graphics.captions`, and `media.finalize(...)`. Return `Result(video=ctx.video_dir / final, caption=..., description="")` (C3 fills the real script + `description` = the subject's sources).
- Keep the ensure-ascii JSON-injection-safe caption composition from explainer intact.

### rules/editorial.md
A short runtime editorial rule capturing the owner's brief: entertainment-first; open on an intriguing hook (a curiosity/fear question in the first seconds); accurate but explained for a lay audience (no jargon beyond essential terms); unfold into hypotheticals about implications; NO on-screen source credit (sources go in the video description). (This guides the C3 script prompt; a copied/adapted `rules/tone.md` is fine too.)

## Scope

- workflows/sensational-science-news/** (new files only)

Do NOT modify: any test, the `explainer` workflow, other source, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`. Do NOT import from `workflows/explainer` (copy helpers instead).

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/registry/test_ssn_workflow.py tests/integration/test_ssn_workflow_dry_run.py -q` passes (discovery + dry-run final.mp4 + subjects shape).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news`, `./.venv/Scripts/python.exe -m ruff format --check .`, project `./.venv/Scripts/python.exe -m mypy` (only the pre-existing PIL error) all clean.
- Print the files you created and a one-paragraph summary.
