# TASK Speech-1 — local narration real mode (Chatterbox TTS + WhisperX alignment)

**Builder:** Cursor. **Product code only** in `sdk/sfvf/media/speech.py` and `sdk/sfvf/_ffmpeg.py`.
Do NOT touch `tests/`, `docs/`, `handoff/`, `mypy.ini`, or `sdk/pyproject.toml` (scaffolding is frozen).
The reviewer contract `tests/sdk/test_speech.py` is FROZEN.

Implement `media.speech.speak` REAL mode: synthesize narration locally (Chatterbox) and force-align the
known text to the audio (WhisperX) for word timings. No key, no network, no paid provider. The `Speech`
return shape and the dry_run path are unchanged.

The heavy GPU libraries MUST stay behind the two module-level seams already stubbed in `speech.py`
(`_synthesize`, `_align`) and be **lazy-imported inside those functions** — never at module top — so CI
(which monkeypatches the seams) never imports torch. The local spike already proved the real libraries
work; your job is the assembly + the seam bodies.

## 1. `sdk/sfvf/_ffmpeg.py` — add `encode_m4a`

Add a helper mirroring the existing style (`silent_audio`/`_run`/`_binary`):
```python
def encode_m4a(src: Path, dest: Path) -> Path:
    """Transcode any audio `src` to AAC/m4a at `dest` (used by real speech synthesis)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run([_binary("ffmpeg"), "-y", "-i", str(src), "-c:a", "aac", "-map_metadata", "-1", str(dest)])
    return dest
```

## 2. `sdk/sfvf/media/speech.py`

**`_synthesize(text, *, voice, model, dest)`** — lazy-import inside the function:
```python
import torch
import torchaudio
from chatterbox.tts import ChatterboxTTS
```
Wrap the import in try/except ImportError raising a clear `RuntimeError` telling the user to install
`sfvf[speech]` (mirror `agents._http_client`'s message). Load the model ONCE and cache it at module level
(e.g. a module global guarded by a lock or a simple `_model is None` check) — do not reload per call.
Choose device `"cuda" if torch.cuda.is_available() else "cpu"`. Generate: `wav = model.generate(text)`;
save `torchaudio.save(str(dest), wav.detach().cpu(), model.sr)`. `voice`/`model` params: accept them; for
this first cut use the default Chatterbox voice/model (a later increment maps `voice` to a reference
sample). Do not log secrets (there are none here).

**`_align(text, audio)`** — lazy-import inside the function:
```python
import whisperx
```
(same ImportError→clear RuntimeError guard). Cache the align model at module level (English). Steps:
`a = whisperx.load_audio(str(audio))`; `total = len(a) / 16000.0`;
`segments = [{"text": text, "start": 0.0, "end": total}]`;
`result = whisperx.align(segments, model_a, metadata, a, device, return_char_alignments=False)`.
Map `result["word_segments"]` → `list[WordTiming]`: for each entry take `word`, `start`, `end`; **skip any
entry missing a numeric `start` or `end`** (WhisperX can drop timings for some tokens) and coerce to
`float`. Return the list.

**`speak(text, *, voice, model)`** real branch (replace the `raise NotImplementedError`):
```python
    ctx.paths.artifacts.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(f"{voice}|{model}|{text}".encode()).hexdigest()[:8]
    wav = ctx.paths.artifacts / f"narration-{sha}.wav"
    dest = ctx.paths.artifacts / f"narration-{sha}.m4a"
    _synthesize(text, voice=voice, model=model, dest=wav)
    encode_m4a(wav, dest)            # from .._ffmpeg
    timings = _align(text, wav)
    duration = probe(dest).duration_s   # from .._ffmpeg
    return Speech(
        audio=dest.relative_to(ctx.paths.video).as_posix(),
        timings=timings,
        duration=duration,
    )
```
Import `encode_m4a` and `probe` from `.._ffmpeg`. You may delete the intermediate `wav` after encoding
(optional; not required by the contract). Call `_synthesize`/`_align` as module-level names (so the tests'
monkeypatch works) — do not inline their bodies into `speak`.

## Rules

mypy-strict clean (the `mypy.ini` ignores for chatterbox/whisperx/torchaudio are already in place). ruff
clean. Do NOT add module-top imports of torch/chatterbox/whisperx (lazy only). Touch only the two files
named.

## Acceptance

`tests/sdk/test_speech.py` passes (5): the 3 dry_run/active-context tests unchanged, plus the two real-mode
tests where the seams are patched — `speak()` must assemble a real `.m4a` (relative path, exists, probes as
audio), a `duration` measured from the produced audio, and `timings` returned by `_align`; and must pass
`text`/`voice`/`model` to `_synthesize` and `text` to `_align`. The rest of the suite still passes.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q tests/sdk/test_speech.py tests/sdk/test_finalize.py
```
(CI never installs chatterbox/whisperx/torch — the tests mock the seams. Pre-existing HyperFrames
`finalize`/`example_workflow` failures in this worktree are the missing toolchain; CI runs them green.)
