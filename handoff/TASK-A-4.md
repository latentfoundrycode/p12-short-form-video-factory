# TASK A-4 — `sfvf.media.speech` dry-run stub

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract `tests/sdk/test_speech.py` is
FROZEN — make it pass by changing product code.

Fourth increment of **Stage A**. Introduces the `sfvf.media` package and its first member,
`media.speech.speak` (SDK §6.4), as a dry-run stub. Follows the A-3 pattern: the returned type is
**JSON-native** so a workflow can cache it via `ctx.step` (SDK §5.5).

Files you may touch: `sdk/sfvf/media/__init__.py` (new), `sdk/sfvf/media/speech.py` (new),
`sdk/sfvf/__init__.py`. Do not add dependencies (audio is generated with the FFmpeg core from A-1).

## 1. The `sfvf.media` package

- `sdk/sfvf/media/__init__.py` — makes `media.speech` reachable: `from . import speech`, and
  `__all__ = ["speech"]`. (Later increments add `graphics`, `finalize`; you only add `speech` now.)
- `sdk/sfvf/__init__.py` — `from . import media`, and add `"media"` to `__all__`.

## 2. `sdk/sfvf/media/speech.py`

```python
speak(text, *, voice, model) -> Speech
```

- `Speech` and its word-timing entry are **`TypedDict`s** (JSON-native, per the A-3 decision):

  ```python
  class WordTiming(TypedDict):
      word: str
      start: float
      end: float

  class Speech(TypedDict):
      audio: str               # path to the audio file, RELATIVE to the video folder (POSIX)
      timings: list[WordTiming]
      duration: float          # real length of the generated audio, in seconds
  ```

- Read the ambient Context with `from .._runtime import current_context` (this module is one level deeper
  than `agents.py`, so `..`). Do not accept `ctx`. The `current_context()` raise on no active context is
  the required behaviour.
- **Dry-run** (`current_context().dry_run`):
  - Derive a plausible `duration` from the text: `words = text.split()`, `duration = max(len(words), 1) /
    RATE` with a fixed `RATE` around `2.5` words/sec. Deterministic.
  - Write silent audio of that duration into `ctx.paths.artifacts` using `sfvf._ffmpeg.silent_audio(dest,
    duration_s=duration)`. Use a **deterministic** filename derived from the inputs (e.g.
    `f"narration-{sha}.m4a"` where `sha` is the first 8 hex of `sha256(f"{voice}|{model}|{text}")`) so the
    same inputs reuse the same name and the result is reproducible. Create `ctx.paths.artifacts` if needed.
  - Return `Speech` with `audio` set to that file's path **relative to `ctx.paths.video`**, as a POSIX
    string (e.g. `"artifacts/narration-<sha>.m4a"`); `duration` the value above; `timings` one entry per
    word, spread evenly across `[0, duration]` (word *i* of *n*: `start = i*duration/n`,
    `end = (i+1)*duration/n`), monotonic and within bounds.
  - The result must be JSON-serializable and deterministic (same `text`/`voice`/`model` → identical
    `Speech`, including the same relative `audio` path — so use the content-derived filename, not anything
    tied to the specific video directory).
- **Not dry-run**: raise `NotImplementedError` with a clear message, e.g.
  `"media.speech.speak: the ElevenLabs adapter arrives in Stage B; run with dry_run=True"`. Do not emit a
  cost event (deferred to Stage C, per `docs/CHANGES.md`).

## Acceptance (the frozen contract `tests/sdk/test_speech.py`)

- `speak` raises (via `current_context`) with no active Context.
- Dry-run: returns a JSON-serializable `Speech` dict whose `audio` is a video-relative path to a real audio
  file; `probe(audio).duration_s ≈ Speech["duration"]` (±0.2s) and the file has an audio track; `timings`
  list the words in order, monotonic and within `[0, duration]`. Same inputs in different video folders
  produce identical `Speech`.
- Not dry-run: raises `NotImplementedError`.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass.
