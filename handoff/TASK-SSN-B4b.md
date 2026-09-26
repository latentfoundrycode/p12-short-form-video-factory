# TASK-SSN-B4b — Voice picker in the launch form (+ its voices-list source)

Add the launch-form voice picker deferred from B1b, now that voices exist. It needs a backend list endpoint (bundled presets + the owner's voice assets) and a Voice `<select>` in `RunLaunchForm` that sends the chosen `voice` in the launch body (the B1a backend already accepts `voice`; the B4a resolver interprets it). Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/sdk/test_speech_voices.py::test_bundled_voice_presets_lists_the_manifest`
- `tests/api/test_library_voices.py`
- `frontend/src/components/RunLaunchForm.test.tsx` (the `describe("RunLaunchForm voice picker")` block)
Keep all existing tests green.

## Part 1 — SDK (`sdk/sfvf/media/speech.py`)

Add a public `def bundled_voice_presets() -> list[dict]` that reads `_voices_root()/"voices.json"` and returns one row per preset: `{"id": f"preset:{p['id']}", "label": p["label"]}` (the manifest's `id` is the stem, e.g. `warm-female` -> row id `preset:warm-female`). Read defensively (missing/corrupt manifest -> `[]`, never raise). ASCII, no torch import at module scope (this function must not import torch).

## Part 2 — backend (`app/api/library.py`)

Add `GET /api/library/voices` -> `{"voices": [{"id", "label", "source"}, ...]}` (a Pydantic response model like the existing ones):
- The bundled presets from `bundled_voice_presets()` (import it from `sfvf.media.speech`), each with `"source": "preset"`.
- Then the owner's VOICE assets: from the owner store, the ACTIVE assets whose `kind == "voice"` -> `{"id": asset.id, "label": <the asset's alias via store.name_for(asset.id) or asset.id>, "source": "asset"}`. Non-voice assets (music/sfx) are NOT listed.
- Order presets first, then owner voice assets. Reuse the existing `_owner_root`/`_owner_store` helpers; tolerate a missing owner pool (just the presets).

## Part 3 — frontend

- `frontend/src/types.ts`: add `export type Voice = { id: string; label: string; source: string };` and add `voice?: string;` to `LaunchBody`.
- `frontend/src/api.ts`: add `export async function fetchVoices(): Promise<Voice[]>` -> `GET /api/library/voices`, returning `data.voices` (same fetch/guard style as `fetchProviderOptions`).
- `frontend/src/components/RunLaunchForm.tsx`: on mount, fetch the voices (like the model-select effect). Render a Voice `<select>` (wrap in the existing `.field`/`.field-label` "Voice" pattern; accessible name matches /voice/i) whose first option is `Default voice` (value `""`) followed by one option per fetched voice (value = its `id`, text = its `label`). Track the selection (default `""`). On submit, include `voice: <selected>` in the `startRun` body. If the fetch FAILS, keep just the `Default voice` option, log nothing to console.error, and keep the form fully usable (Start run still works, sending the default voice). Do not change the existing Approval mode / Per-video budget / Video count / param controls.

## Scope

- sdk/sfvf/media/speech.py
- app/api/library.py
- frontend/src/types.ts
- frontend/src/api.ts
- frontend/src/components/RunLaunchForm.tsx

Do NOT modify: any test, the bundled assets, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`. Do NOT import `app.*` into the SDK.

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/api/test_library_voices.py tests/sdk/test_speech_voices.py tests/api/test_library_api.py -q` passes.
- `npm --prefix frontend run test -- --run` passes (incl. the voice-picker block + all existing RunLaunchForm tests), and `npm --prefix frontend run lint` + `npm --prefix frontend run typecheck` clean.
- `./.venv/Scripts/python.exe -m ruff check app/api/library.py sdk/sfvf/media/speech.py`, `./.venv/Scripts/python.exe -m ruff format --check .`, project `./.venv/Scripts/python.exe -m mypy` (only the pre-existing PIL error) all clean.
- Print the files you changed and a one-paragraph summary.
