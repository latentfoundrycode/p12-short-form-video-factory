# TASK-SSN-D3b — Owner music mix + sanitized-sources description

## Context

Two finishing pieces of `run()`:
1. AUDIO — if the owner has granted an active MUSIC library asset to this workflow, mix it (ducked)
   under the narration via `media.edit.mix`; otherwise degrade gracefully to narration-only.
2. DESCRIPTION — `Result.description` lists the video's SOURCES (researched article URLs + web-image
   source URLs), SANITIZED (http/https only, de-duplicated, order preserved; drop `javascript:`/`data:`
   etc.). Security carry-forward from the D2 review: the web-image URLs are untrusted.

Plus a small robustness fix carried from D2.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

`import shutil` (stdlib) is allowed. No other new third-party imports. Do not touch tests, SDK, other
workflows, or deps. Stay in this checkout.

## Frozen tests to make green (read them first)

- `tests/integration/test_ssn_assemble.py` (4 tests): `_sanitize_source_urls`, `_video_description`,
  `_select_music`.
- Keep `tests/integration/test_ssn_visual_bed.py`, `test_ssn_composite.py`, `test_ssn_captions.py`,
  `test_ssn_workflow_dry_run.py` green.

## What to build

### 1. `_sanitize_source_urls(urls) -> list[str]`

For each url: `str(url).strip()`, parse with `urlsplit`, KEEP only if `scheme in ("http", "https")`;
de-duplicate preserving first-seen order. Return the cleaned list. (Drops `javascript:`, `data:`,
`ftp:`, empty, etc.)

### 2. `_video_description(article_urls: list[str], image_urls: list[str]) -> str`

Sanitize both lists with `_sanitize_source_urls`. Build a plain-text description:
- if any article URLs: a `Sources:` heading followed by one `- <url>` per line;
- if any image URLs: an `Image sources:` heading followed by one `- <url>` per line.
Join the sections with a blank line; omit an empty section; return `""` when both are empty. Plain text
only (the run view renders it as text, React-escaped — do not emit HTML).

### 3. `_select_music(ctx) -> str | None`

- `assets = [a for a in ctx.library.find(status="active") if getattr(a, "kind", None) == "music"]`
  (guard `ctx.library is None` -> return None).
- If none, return None (narration-only).
- Take the first; `src = ctx.library.path(asset.id)`; if `src is None`, return None.
- Copy the blob into artifacts and return a VIDEO-RELATIVE path `media.edit.mix` can resolve:
  `dest = ctx.paths.artifacts / f"music{src.suffix}"; shutil.copyfile(src, dest);
  return f"artifacts/music{src.suffix}"`.

### 4. Wire into `run()` (after the visual-bed step; at the finalize tail)

- Music + mix:
  ```python
  music_rel = _select_music(ctx)
  narration_audio = speech["audio"]
  audio = media.edit.mix(narration_audio, music=music_rel, duck=True) if music_rel else narration_audio
  ```
  Then `final = media.finalize(visual, audio=audio, captions=captions)` (was `audio=speech["audio"]`).
- Description (recall `sources` is already `ctx.shared["sources"].get(subject, [])` at the top of run):
  ```python
  article_urls = [str(s.get("url", "")) for s in sources]
  description = _video_description(article_urls, bed["source_urls"])
  ```
  Return `Result(video=ctx.video_dir / final, caption=_caption(narration), description=description)`.

### 5. Make the clip cap explicit (D2 carry-forward)

In `_source_visual_bed`, after building `clip_indices`, enforce the ceiling explicitly rather than
relying on the `{0}`+last construction: e.g. keep at most `_MAX_CLIPS` of them
(`clip_indices = set(sorted(clip_indices)[:_MAX_CLIPS])`). Behaviour is unchanged today; this makes the
paid-clip ceiling robust to future edits and actually reads `_MAX_CLIPS`.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_assemble.py tests/integration/test_ssn_visual_bed.py -q` — all pass.
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_workflow_dry_run.py -q` — still
  green (the dry-run pipeline renders, mixes narration-only since there is no library music in dry-run,
  and produces a Result whose description lists the dry-run stub source URLs).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and
  `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — clean (no new errors from `main.py`).

Print the three new helpers and the updated `run()` tail.
