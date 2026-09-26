# TASK-SSN-B4a — Selectable voices in media.speech (resolver + isolation wiring + denoise)

Wire voice selection + cloning into `sdk/sfvf/media/speech.py`, using the probe findings (recorded in docs/PROJECT_STATUS.md): Chatterbox re-conditions cleanly whenever a call passes a reference clip, but a prompt-less `generate()` retains the previous voice; and the owner's chosen noise fix is a gentle denoise on the OUTPUT (cleaning the reference muffles). The bundled preset clips already exist under `assets/voices/` (warm-female.wav [default], literary-female.wav, classic-male.wav, default.wav + voices.json). Edit ONLY `sdk/sfvf/media/speech.py`. Make the supervisor-authored frozen tests green WITHOUT editing them:
- `tests/sdk/test_speech.py` (real-mode tests now pass a resolved `voice_clip` to the seam)
- `tests/sdk/test_speech_voices.py` (resolver, denoise, preset precedence, owner-asset, safety)
Keep the dry-run tests in test_speech.py green (dry-run behaviour is UNCHANGED).

## 1. Voice resolver

Add `_voices_root() -> Path` returning the bundled voices dir via the install-root walk like graphics.py: `Path(__file__).resolve().parents[3] / "assets" / "voices"`.

Add `_resolve_voice(ctx, voice: str) -> Path` returning a reference clip path. It must NEVER return None and must never point outside the bundled dir for preset/default cases:
- `voice == ""` -> `_voices_root() / "default.wav"`.
- `voice.startswith("preset:")` -> stem = the part after `preset:`; if stem is a safe segment and `_voices_root()/f"{stem}.wav"` exists -> that file; else the default. (The `preset:` prefix FORCES the bundled preset -- it must NOT consult owner assets. delta A5 precedence.)
- otherwise (a bare id/name): first try a granted owner voice asset -- `p = ctx.library.path(voice)`; if `p` is not None and exists -> `p`. Else if `voice` is a safe segment and `_voices_root()/f"{voice}.wav"` exists -> that bundled preset. Else -> the default.
- SAFETY: treat a segment as safe only if it contains no path separators (`/`, `\`), is not `.`/`..`, contains no `..`, and matches `^[A-Za-z0-9._-]+$`. An unsafe `voice`/stem never touches the filesystem as a path component -> return the default. (ctx.library.path already validates/By-id resolves owner assets; do not pass an unsafe raw string into a filesystem join.)

## 2. Isolation wiring in the synth seam

Change `_synthesize` to take the resolved clip, not a raw id/model:
`def _synthesize(text: str, *, voice_clip: Path, dest: Path) -> None:` -- it ALWAYS calls `_tts_model.generate(text, audio_prompt_path=str(voice_clip))` (never prompt-less), then saves. Keep the lazy-import seam, the `_tts_lock`, and the model caching. (The default voice is a bundled clip, so every real call has an explicit prompt -> full per-call isolation, per the probe.)

## 3. Gentle output denoise

Add `def _denoise(src: Path, dest: Path) -> None:` that runs the owner-approved gentle filter on the synth OUTPUT via the shared ffmpeg helper (`sfvf._ffmpeg._run`/`_binary`): `-af "highpass=f=70,afftdn=nr=12:nf=-30"`, mono/24k preserved, deterministic. Do NOT denoise reference clips.

## 4. speak() real branch (dry-run stays as-is)

In the REAL branch only:
1. `clip = _resolve_voice(ctx, voice)`.
2. Cache key on the RESOLVED CLIP's CONTENT HASH (delta A1): compute `clip_hash = sha256(clip.read_bytes())` and build the artifact stem as `sha256(f"{clip_hash}|{model}|{text}")[:8]` (replaces the old `voice|model|text` key), so the same voice id pointing at different clip bytes does not collide.
3. `_synthesize(text, voice_clip=clip, dest=raw_wav)`.
4. `_denoise(raw_wav, clean_wav)` (a distinct file).
5. `encode_m4a(clean_wav, dest_m4a)`; then `_align`, the empty-timings fail-closed check, and `probe` duration -- all UNCHANGED.
Keep the `speak(text, *, voice, model)` public signature (workflows pass both; `model` stays in the cache key).

## Scope

- sdk/sfvf/media/speech.py

Do NOT modify: any test, the bundled assets/voices/ files, other source, `docs/`, `handoff/`, dependencies. Do NOT run `npm run build`. Do NOT import from `app.*` (SDK stays app-independent -- implement the safe-segment check locally).

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_speech.py tests/sdk/test_speech_voices.py -q` passes (dry-run + real seam + resolver + denoise + precedence + owner-asset + safety).
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/media/speech.py`, `./.venv/Scripts/python.exe -m ruff format --check .`, project `./.venv/Scripts/python.exe -m mypy` (only the pre-existing PIL error) all clean.
- Print the file you changed and a one-paragraph summary.
