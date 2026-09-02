# TASK A-7 — the example workflow (Stage A capstone)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`,
`docs/`, or `handoff/`. The reviewer contract `tests/integration/test_example_workflow.py` is FROZEN —
make it pass by writing the workflow it drives.

Final increment of **Stage A**. Build the first real workflow, `workflows/explainer/`, a composition
explainer that uses the whole provided-functions surface built in A-3…A-6 and produces a finished video in
dry-run at zero cost. It is the integration proof that the SDK and the execution engine work together.

Files you may create: `workflows/explainer/workflow.toml`, `workflows/explainer/main.py`. Do not touch
anything else. Do not add dependencies.

## Ground rules for this workflow

- **Gate-free.** Do NOT call `ctx.gate(...)` — gate answering is not wired until Stage F, so a gate would
  block forever. (The §11.1 example has a gate; omit it here.)
- **Every expensive call is wrapped in a cached `ctx.step`**, and **every step's `inputs` are deterministic**
  (functions of params/topic/script only — never the clock, `ctx.run_id`, or a timestamp), so a second run
  reuses the cache. Provided-function results are JSON-native (dicts/strings), so `step.set(...)` caches them.
- **The composition uses neither the real clock nor unseeded randomness** (§6.5) — build the HTML
  deterministically from the script and timings.

## 1. `workflows/explainer/workflow.toml`

```toml
[workflow]
id = "explainer"
name = "Explainer"
version = "1.0.0"
entrypoint = "main:run"
prepare = "main:prepare"
sdk = "1"
video_semantics = "variants"

[output]
aspect = "9:16"
fps = 30
safe_zone = "tiktok"

[[params]]
key = "topic"
type = "text"
label = "Topic"
required = false
help = "Leave empty to let the agent choose one."

[[params]]
key = "duration_s"
type = "number"
label = "Duration (seconds)"
default = 30
affects_cost = true

[[params]]
key = "voice"
type = "text"
label = "Narrator voice"
default = "narrator"
```

## 2. `workflows/explainer/main.py`

Import from the SDK: `from sfvf import Context, Result, agents, media`. Two entry points:

**`prepare(ctx: Context) -> dict`** — runs once for the request; the shared topic + research belong here:
- A `choose-topic` step keyed on `{"given": <the topic param or "">}`: if the param is set, use it; else
  `agents.llm("Pick one topic worth explaining.", agent="researcher", model="stub-llm")`. Store the chosen
  topic with `step.set(...)`; read it back as `step.value` after the `with`.
- A `research` step keyed on `{"topic": topic, "as_of": date.today().isoformat()}` (the date bucket keeps
  stale results a decision, per §6.1): `step.set(agents.research(topic))`.
- Return `{"topic": topic, "sources": <research result>}` (JSON-serializable — `agents.research` returns
  JSON-native `Source` dicts).

**`run(ctx: Context) -> Result`** — once per video:
- `topic = ctx.shared["topic"]`.
- A `script` step keyed on `{"topic": topic, "variant": ctx.video_index, "duration": ctx.params["duration_s"]}`
  (variant on `video_index` so each of several videos gets a different script):
  `step.set(agents.llm(f"Write a {ctx.params['duration_s']}-second script on {topic}.", agent="scriptwriter",
  model="stub-llm"))`. Read `script = step.value`.
- A `speech` step keyed on `{"script": script, "voice": ctx.params["voice"]}`:
  `step.set(media.speech.speak(script, voice=ctx.params["voice"], model="stub-tts"))`. `speech = step.value`
  is a JSON-native dict with `["audio"]` (a video-relative path), `["timings"]`, `["duration"]`.
- Build the composition HTML deterministically from `script`, `speech["timings"]`, and
  `media.graphics.safe_zone_css()` (a small local helper is fine — e.g. a string that embeds the script text
  and `@import`s the CSS path). Building HTML is cheap, so it is NOT in a step.
- A `render` step keyed on `{"html": html}`:
  `step.set(media.graphics.render(html, duration_s=speech["duration"]))`. `visual = step.value` is a
  video-relative path string.
- `captions = media.graphics.captions(speech["audio"], speech["timings"], style="bold")` (cheap, not a step).
- `final = media.finalize(visual, audio=speech["audio"], captions=captions)` — the mandatory last step;
  returns the video-relative string `"final.mp4"`.
- `return Result(video=ctx.video_dir / final, caption=<a short caption derived from the script>)`.
  **Note the `ctx.video_dir / final`:** `finalize` returns a video-relative *string*, but `Result.video` is a
  `Path` — join it to `ctx.video_dir` so the runner records the right path. (Do not pass the bare string.)

The `ctx.step` usage pattern (both entries):

```python
with ctx.step("script", inputs={...}) as step:
    if not step.cached:
        step.set(agents.llm(...))
script = step.value
```

## Acceptance (the frozen contract `tests/integration/test_example_workflow.py`)

Driven through the real supervisor (`run_request`, dry-run, `video_count=1`):
- The request and the one video both reach status **complete**; `video.json`'s `result["video"] == "final.mp4"`.
- `runs/explainer/<run>/01/final.mp4` exists and is a valid **1080×1920** video with `duration > 0`.
- `script`, `speech`, and `render` step events are emitted.
- A **second** run against the same `cache_dir` re-runs nothing: every `step` event reports `status == "cached"`.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

`mypy.ini` checks `app, sdk, tools` — **not** `workflows/` — so the workflow itself is outside the mypy
gate (workflow code is free-form per the plug-in boundary). Still, `ruff check`/`ruff format` DO cover
`workflows/`, so keep `main.py` clean and formatted. Do not weaken, skip, or edit any test to make the gate
pass.
