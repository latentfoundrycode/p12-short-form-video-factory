# TASK-SSN-B3 — Audio mixer `media.edit.mix` (narration + ducked music + offset SFX)

Implement `media.edit.mix` in `sdk/sfvf/media/edit.py`: mix a narration track with an optional music bed (ducked under the narration) and optional offset SFX into ONE audio track. Use an ffmpeg `sidechaincompress` filtergraph — the KP-008 probe (recorded in docs/PROJECT_STATUS.md) showed it yields ~14 dB of ducking and a single-stream output; kinocut's ducking primitives are unverified (`audio_compose` hung in §9.3), so do NOT use them. Make the supervisor-authored frozen test green WITHOUT editing it: `tests/sdk/test_edit_mix.py`. Keep the existing edit tests (trim/cut) green.

## Signature

```
def mix(
    narration: str,
    *,
    music: str | None = None,
    sfx: list[tuple[str, float]] | None = None,
    duck: bool = True,
) -> str:
```

- Returns the video-relative path of the mixed audio (an artifact under `ctx.paths.artifacts`), like `trim`/`cut` return `_artifact(...)` rel paths.
- `narration` is required; `music` optional; `sfx` is an optional list of `(path, at_seconds)` placed at those offsets; `duck` toggles sidechain ducking of the music under the narration.

## Behaviour

- `ctx = current_context()`. Resolve EACH input path with `(ctx.paths.video / p).resolve()` — this handles both a video-relative artifact path (narration, produced upstream) AND an absolute path (a granted library asset from `ctx.library.path(...)` for music/SFX): pathlib drops the left operand when the right is absolute, so one form works for both. Follow the existing first-party-trust model of `trim`/`cut` (no extra containment check).
- Build via `_artifact(ctx, f"edit-mix-{_sha8([...])}.m4a")` (aac). Wrap the ffmpeg run in `heartbeat_during("edit", waiting_on="ffmpeg")` like `trim`/`cut`, and run through the shared ffmpeg helper (`sfvf._ffmpeg._run` / `_binary`) rather than kinocut.
- Filtergraph (ffmpeg `-filter_complex`), inputs in order narration, then music (if given), then each sfx:
  - Normalise every input to a common form before mixing (e.g. `aresample=44100` + `aformat=channel_layouts=stereo`) so amix is clean for stereo music + mono narration.
  - If `music` and `duck`: split narration `[0:a]asplit=2[nsc][nmix]`; duck the music `[<music>][nsc]sidechaincompress=threshold=0.02:ratio=12:attack=20:release=250[duckm]`; the narration mix-copy is `[nmix]`.
  - If `music` and not `duck`: use the music as-is (no sidechaincompress); narration used directly in amix (no asplit needed).
  - Each sfx i at offset `at`: `[<sfx_i>]adelay={round(at*1000)}:all=1[sfx_i]`.
  - Final: `amix=inputs=K:duration=longest:normalize=0[out]` over {narration, ducked-or-plain music if present, each delayed sfx}. `-map "[out]"`, encode aac (`-c:a aac -b:a 192k`).
  - When `music is None and sfx is None`: just re-encode the narration to the output (single track, same duration).
- The output must be exactly ONE audio stream; its duration is the longest input (amix `duration=longest`).

## What the frozen test verifies (so the contract is clear)

- One audio stream out; duration ≈ 6.0s (longest input).
- `duck=True`: the 800 Hz music-band mean level while narration plays [2.2,3.8]s is ≥ 6 dB LOWER than where narration is silent [4.4,5.6]s (measured via band-limited `volumedetect`).
- `duck=False`: the 800 Hz band is roughly flat across those windows (≤ 3 dB difference).
- Offset SFX: 1200 Hz band level at [1.0,1.3]s (where a `(sfx, 1.0)` is placed) is ≥ 6 dB above [4.0,4.3]s.
- Narration-only mix returns a valid single-stream track.
- No active context -> RuntimeError (via `current_context()`).

## Scope

- sdk/sfvf/media/edit.py

Do NOT modify: any test, other source, `docs/`, `handoff/`, dependencies. (kinocut is already an optional dep; you are NOT using it here — use ffmpeg directly.)

## Constraints

- Workspace boundary; ASCII in Python; one paragraph is one line in Markdown. Record any tooling friction / defect in `docs/BUILDER_NOTES.md`.

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/sdk/test_edit_mix.py -q` passes (all cases).
- `./.venv/Scripts/python.exe -m ruff check sdk/sfvf/media/edit.py` clean, `./.venv/Scripts/python.exe -m ruff format --check .` all formatted, project `./.venv/Scripts/python.exe -m mypy` clean (only the pre-existing PIL error).
- Print the file you changed and a one-paragraph summary.
