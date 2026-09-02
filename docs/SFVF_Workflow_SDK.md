# SFVF — Workflow Authoring Guide & SDK Reference

**Version:** 2.3
**Companion to:** SFVF Product Requirement Document v2.3, SFVF Architecture Blueprint v2.3
**Audience:** Whoever writes a workflow plug-in — a person, or an AI coding assistant being directed by one.

Read this before writing a workflow. Everything described here is fixed contract. Anything not described here is yours to decide however you like.

---

## 0. Terms used in this document

**Workflow (plug-in).** A folder containing a manifest and program code, producing one specific kind of video.

**Manifest.** The `workflow.toml` file in which a workflow declares facts about itself. It contains no logic.

**Chassis.** The parts of SFVF shared by all workflows: running them, paying for them, remembering results, saving output.

**SDK.** The library the chassis installs into your workflow's environment. It gives you the context object and the ready-made functions for speech, video, graphics and editing.

**Context (`ctx`).** An object handed to your code when it runs, carrying your settings, your file paths, and every chassis function you are allowed to use.

**Step.** A unit of work whose result the chassis remembers. Explained fully in §5, which is the most important section here.

**Family.** The name a step is given, identifying the *kind* of work it does. Sixty shots in one episode are sixty steps of one family. Recovery options, time limits and statistics all match on the family.

**Cache.** Stored results of previous steps, reused when the same work is requested again — including across different runs on different days.

**Library.** A durable store of reusable assets belonging to a body of work rather than to any one run: character sheets, location references, style plates. Unlike the cache it is named, described, never evicted, and unaffected by version changes. Explained in §7.

**Asset.** One item in the library: a file, plus a descriptor. Identified by the hash of its contents, which is what makes "which version of this was used in episode 7" answerable.

**Descriptor.** The metadata beside an asset — tags, facets, a written description, caveats, and how it was made. It is what selection reads, so that choosing between assets is a text operation rather than a paid visual one.

**Facet.** One declared, structured metadata key on an asset, such as `subject` or `outfit`. Facets are yours to define; the chassis filters on them and understands nothing about them.

**Namespace.** The library a workflow reads and writes. Several workflows may share one, which is how a shorts workflow and a longform workflow share a cast.

**Pure function.** A piece of code whose output depends *only* on the inputs you hand it. Given the same inputs it always produces the same output, and it does not secretly consult anything else. This concept matters enormously for steps; §5 explains why.

**Deterministic.** Producing the same result every time from the same input. HyperFrames renders are deterministic; AI generation generally is not.

**JSON-serializable.** Data that can be written out as plain text in JSON format — numbers, strings, true/false, lists and dictionaries of those things. A file path can be stored this way; an open file cannot.

**Context manager.** The Python `with` construction. It runs some setup, gives you a block of code, and then runs some cleanup afterwards even if that code fails. Steps use it so that results get saved and cancellation gets checked without you having to remember to do either.

**Frontmatter.** A block at the very top of a markdown file, fenced by three dashes, holding structured settings rather than prose.

**Stub.** A fake, free stand-in returned instead of calling a paid service, used in dry-run mode.

**Gate.** A point where your workflow pauses and waits for the user before continuing. A gate returns a decision, which may be more than approve-or-not.

**Forecast.** A workflow's own statement of what the rest of the run will cost, made once it knows something the chassis could not have known in advance — such as how many shots the script turned out to need.

---

## 1. What a workflow is, and what it is not

A workflow encodes **one specific kind of video** — what it says, what it looks like, how it is cut together. Most will be short-form and vertical; some will not, and the manifest says which.

It does **not** handle money, retries, caching, storing secrets, reporting progress, encoding the final file, or organising output folders. All of that is the chassis's job. If you find yourself writing code of that kind, you are almost certainly duplicating something the SDK already provides, and your version will be worse because it will not integrate with the budget system or the records.

### Minimum structure

```
workflows/my-workflow/
├─ workflow.toml          # required — the manifest
├─ requirements.txt       # required — may be empty
├─ main.py                # required — your code
├─ thumbnail.png          # optional — shown on the card
├─ criteria/              # optional — what "good" means, for learning
├─ rules/                 # optional — instructions for your agents
├─ skills/                # optional — reference material for your agents
├─ stubs/                 # optional — dry-run stand-ins only your workflow needs
└─ *.toml, *.json         # optional — your own hand-edited config, e.g. cast.toml
```

Your own configuration files are welcome here and are read-only at run time like everything else in this folder. They are the right home for settings that are too numerous or too stable to belong in the Run pop-up — the mapping from eight characters to eight ElevenLabs voice identifiers, for instance. See §6.4.

Reusable *assets* do not live here. They live in the library, which is outside your folder because it is written to while running. See §7.

---

## 2. The manifest: `workflow.toml`

```toml
[workflow]
id          = "news-explainer"     # must equal the folder name; permanent
name        = "News Explainer"     # display label; change freely
version     = "1.3.0"              # increase whenever behaviour changes
description = "Researches a topic and produces a 45-second explainer."
thumbnail   = "thumbnail.png"
entrypoint  = "main:run"           # file:function
prepare     = "main:prepare"       # optional; file:function
python      = "3.12"
sdk         = "1"                  # SDK major version this was written against

# What the number-of-videos setting means for this workflow. See §2.6.
video_semantics = "variants"       # "variants" (default) | "sequence"
max_videos      = 10               # optional cap; omit for no cap
atomic          = false            # true if a half-finished video is worthless
safety_factor   = 1.25             # only meaningful when atomic

requires_binaries = ["ffmpeg", "ffprobe"]

# Capabilities your workflow cannot run without. Checked before Initiate. See §2.9.
requires_capabilities = ["agents.vision"]

[[requires_keys]]
name  = "OPENROUTER_API_KEY"
label = "OpenRouter"

[[requires_connections]]
name  = "higgsfield"
label = "Higgsfield"
kind  = "mcp_oauth"

# ---- What shape the finished video is. See §2.7. ----

[output]
aspect    = "9:16"
fps       = 30
safe_zone = "tiktok"               # "tiktok" | "none"

# ---- The library this workflow reads and writes. See §7. ----

[library]
namespace = "news-explainer"       # defaults to the workflow id

[[library.facets]]
key    = "subject"
values = "open"

[[library.facets]]
key    = "view"
values = ["turnaround-8pt", "expression-sheet", "closeup", "prop-only"]

# ---- Per-family time limits. See §2.8. ----

[[limits]]
step    = "generate-shot"
seconds = 900

# ---- Settings shown in the Run pop-up, in this order ----

[[params]]
key      = "topic"
type     = "text"
label    = "Topic"
required = false
help     = "Leave empty to let the research agent choose one."

[[params]]
key          = "video_model"
type         = "select"
label        = "Video model"
affects_cost = true
options_from = "higgsfield.video_models"   # filled in when the pop-up opens

[[params]]
key          = "voice"
type         = "select"
label        = "Narrator voice"
options_from = "elevenlabs.voices"         # includes your own cloned voices

[[params]]
key          = "duration_s"
type         = "number"
label        = "Target duration (seconds)"
default      = 45
min          = 20
max          = 90
affects_cost = true

# ---- Options offered when a step runs out of retries ----
# `step` names a step FAMILY, so one entry covers all sixty shots.

[[recovery]]
step   = "generate-shot"
label  = "Switch to the standard video model and retry"
action = "set_param"
param  = "video_model"
value  = "standard"

# ---- Questions the user answers about each finished video ----

[[quality_factors]]
key      = "hook"
question = "Did the first two seconds make you want to keep watching? Why?"

[[quality_factors]]
key      = "coherence"
question = "Did the visuals stay consistent across shots? Where did they drift?"
```

### 2.1 Why `id` is permanent and `name` is not

The identifier is what links a workflow to its output folder under `runs/`. Changing it would orphan every video the workflow has ever produced, because SFVF would look for the history under a name that has no folder. The display name is used only for showing on screen, so it can change whenever you like.

### 2.2 Settings types

Available: `text`, `textarea`, `number`, `bool`, `select`, `multiselect`, `file`.

Fields available on all of them: `key`, `type`, `label`, `required`, `default`, `help`, `affects_cost`.
Type-specific fields: `min`, `max`, `step` for numbers; `options` or `options_from` for choices; `placeholder` for text; `accept` for files; `unit` on numbers, shown beside the field rather than typed into it.

### 2.2a Choice lists that come from a provider

A `select` or `multiselect` may declare `options_from` instead of a literal `options` list. The chassis then asks the relevant provider adapter for the current choices when the Run pop-up opens.

Use it for anything that lives in the account rather than in your workflow. `elevenlabs.voices` returns every voice the key can reach, including voices the user cloned themselves, which by definition cannot appear in a manifest you wrote. `higgsfield.video_models` returns what Higgsfield currently offers, which is a moving target: the platform fronts thirty or more models and its own command-line client fetches the list from the backend rather than hard-coding it.

Two things are worth knowing about how this behaves.

**The identifier is what gets recorded, not the label.** Providers rename things. A value recorded as a pinned identifier still resolves in a year; one recorded as "Premium" does not.

**A stale list does not block a run.** If the provider cannot be reached the last known list is offered, marked as stale. An identifier from an older run that no longer appears is still shown, marked as no longer offered, rather than quietly falling back to something else.

Do not write your own model or voice list into `options` as a shortcut. It will be wrong within a month and the failure is silent: the run works, it just never offers the voice the user actually wanted.

### 2.3 `affects_cost`, and why getting it wrong breaks estimates

Before a run starts, SFVF estimates its cost by finding the last ten comparable runs. "Comparable" means matching on the settings marked `affects_cost = true`.

Mark the settings that genuinely change the price: which model is used, how long the video is, how many shots there are.

**Never mark a free-text field.** A topic is different on every single run, so if it were included in the matching, no two runs would ever be considered comparable and the estimate would permanently fall back to a crude average. This is a quiet failure — the estimate still appears, it is just always the least useful version of itself.

### 2.4 Settings you must not declare

SFVF adds these to every Run pop-up automatically: the number of videos, the budget, the maximum retries, the video concurrency, the parallel-steps-per-video setting, and the dry-run switch. Declaring your own version of any of them is an error.

### 2.5 Recovery options

These are declared in the manifest rather than produced at the moment something fails, so that the user can see what the fallbacks are before starting rather than being surprised by a list of options mid-run.

`step` names a **family**, not one particular step. A workflow generating sixty shots declares one recovery entry, not sixty.

### 2.6 What "number of videos" means: `video_semantics`

The default, `"variants"`, is the original behaviour: N videos on one topic, independent of each other, produced concurrently, ranked against one another afterwards. Make five, keep the good ones.

`"sequence"` says the videos are episodes rather than alternatives. Under it:

- Videos run **strictly in order**, regardless of the concurrency setting.
- `ctx.previous` gives you the preceding video's `Result.extra`, so episode 4 can read where episode 3 left off.
- A failure **stops** the remaining videos rather than letting them proceed. This is the opposite of the variants rule and is right for the same reason the variants rule is right: episode 5 cannot be made without episode 4, so producing it would be producing nonsense.

`max_videos` caps the setting in the pop-up. Set it to 1 for anything expensive enough that "produce several and discard most" is not a strategy you would actually use.

**Continuity across Generation Requests** is not what `sequence` is for. It only spans one request. If episode 8 is its own request, its starting state comes from the library (§7), not from `ctx.previous`.

### 2.6a `atomic`, for workflows where a partial video is worthless

Set `atomic = true` when an incomplete video has no value at all — a drama episode missing its last twenty shots, as opposed to a set of variants where four out of five is a fine afternoon.

It changes four things:

1. Pre-flight reserves the **whole** estimated run rather than spending incrementally, and Initiate is blocked if the available balance is below the estimate multiplied by `safety_factor`.
2. Running out of budget mid-run **stops cleanly** at a step boundary rather than prompting and limping on. Everything finished is kept, so resuming after a top-up asks only for the price of what remains.
3. `partial` is not a possible outcome. A request with an incomplete video ends `stopped` or `failed`.
4. A scheduled run skips if pre-flight fails, and stops rather than skipping forward if the budget runs out mid-run.

### 2.7 `[output]` — the shape of the finished video

Not every workflow makes a 9:16 clip for a platform that covers the corners with its own interface. Declare what you are actually making:

| Key | Values | Effect |
|---|---|---|
| `aspect` | `"9:16"`, `"16:9"`, `"1:1"` | Resolution used by `finalize()`; what `safe_zone_css()` returns |
| `fps` | integer | Frame rate applied at finalise |
| `safe_zone` | `"tiktok"`, `"none"` | Whether platform margins are reserved and enforced |

The self-review thresholds follow from this too. The "is this effectively a slideshow" check is calibrated per format, because a slow establishing shot in a six-minute episode is not the failure that the same measurement would indicate in a forty-five-second short.

Omitting `[output]` gives you 9:16, 30fps, `tiktok` — the v2.2 behaviour.

### 2.8 `[[limits]]` — per-family time limits

The supervisor kills and retries a step that has produced no sign of life for too long. The default limit is global; a family that legitimately takes much longer declares its own.

```toml
[[limits]]
step    = "generate-shot"
seconds = 900
```

**The limit measures silence, not elapsed time.** Every SDK function that waits on a provider emits a heartbeat while it polls, and each heartbeat resets the timer. So a paid video job that takes eleven minutes is never killed, while a workflow that has genuinely hung still is. This distinction matters more than it sounds: killing and retrying a step with an outstanding paid job means paying twice and discarding the first result when it eventually arrives.

Declaring a limit for a family that does not exist is a validation error, because it is nearly always a typo in the family name and would otherwise silently leave that step on the default.

### 2.9 `requires_capabilities`

Some workflows depend on provider abilities that may not exist: conditioning a generation on reference images, generating stills at all, showing an image to a language model. Declare what you need:

```toml
requires_capabilities = ["image.generate", "video.refs", "agents.vision"]
```

Adapters declare what they support; the registry checks at scan time; a workflow needing something unavailable shows a blocked badge naming the missing capability. This follows the standing principle that anything knowable before a run starts should block Initiate with a specific message rather than failing expensively in the middle.

---

## 3. Entry points

```python
from sfvf import Context, Result

def prepare(ctx: Context) -> dict:
    """OPTIONAL. Runs once per Generation Request, before any video.

    Use it for work every video shares: choosing the topic, doing one
    research pass, provisioning character references into the library.

    Library WRITES belong here rather than in run(), because run() calls
    may execute concurrently. See §7.5.

    Whatever you return must be JSON-serializable, and reaches every
    later call as ctx.shared. Files belong in ctx.shared_dir."""
    ...

def run(ctx: Context) -> Result:
    """REQUIRED. Runs once per video."""
    ...
    return Result(video=ctx.video_dir / "final.mp4", caption="…")
```

### 3.1 Why `run()` is called once per video rather than once for all of them

The alternative — handing the workflow a count and letting it loop internally — was considered and rejected. Calling once per video gives three things. A failure on video three does not take videos four and five down with it. Each video can be stopped and resumed independently, because each has its own folder and its own saved step results. And SFVF, not the workflow, controls how many run at the same time, which means concurrency is a user setting rather than something each workflow reimplements.

Under `video_semantics = "sequence"` the first of those three reverses: a failure does stop the rest, because the rest depend on it. The other two are unchanged.

`prepare()` exists so that the shared, expensive beginning is not paid for once per video. Without it, a research pass feeding five videos would be performed five times.

Parallelism *within* one video — sixty independent shots in one episode — is not what the concurrency setting controls. That is `ctx.map()`, §4.7.

### 3.2 Where topic selection belongs

Every video in a Generation Request shares one topic. If your workflow lets the research agent choose the topic, that choice belongs in `prepare()`. Putting it in `run()` would give each video a different topic, which is not what a Generation Request means.

### 3.2a Reading the previous episode

Under `sequence`, `ctx.previous` holds the `Result.extra` of the video before this one, or `None` for the first. Use it to carry plot state forward. It is `None` in `variants` mode, where it would be meaningless.

State that must survive *between* Generation Requests belongs in the library instead — see §7.6.

### 3.3 What `Result` carries

| Field | Required | Notes |
|---|---|---|
| `video` | yes | Path to the finished file |
| `caption` | no | Generated by your workflow; the chassis does not write captions |
| `hashtags` | no | A list of strings |
| `cover_frame_s` | no | Defaults to 1.0 seconds |
| `notes` | no | Free text, displayed in the video's detail view |
| `extra` | no | A dictionary, recorded exactly as given |

### 3.4 On failing

If your code raises an error, that video is marked failed, the details are recorded, and the other videos carry on — except under `sequence`, where the videos after it are not attempted.

**Do not write defensive code that catches errors and returns a broken video anyway.** SFVF's whole approach to failure is statistical: produce several, keep the good ones, discard the rest. A workflow that hides its failures behind a returned file corrupts that, because a broken video that claims to have succeeded will be counted as a success and may be ranked against good ones. Let it raise.

---

## 4. The context object

This is the complete supported surface. Anything not listed here is not part of the contract and may change without warning.

### 4.1 Identity and paths

```python
ctx.workflow_id, ctx.workflow_version
ctx.run_id                # e.g. "20260810-143022"
ctx.video_index           # 1-based: this is video 1, 2, 3…
ctx.video_count           # how many videos this request is producing
ctx.video_dir             # runs/<workflow>/<run>/01/
ctx.artifacts             # …/01/artifacts/ — put intermediate files here
ctx.shared                # whatever prepare() returned
ctx.shared_dir            # shared files from prepare()
ctx.workflow_dir          # your own folder — read only, never write here
ctx.previous              # prior video's Result.extra; None outside "sequence"
ctx.step_concurrency      # the user's parallel-steps setting; pass to ctx.map()
```

Put intermediate files in `ctx.artifacts` rather than a temporary folder of your own. They then appear in the video's detail view, which is what makes a bad output diagnosable afterwards — you can look at the script, listen to the narration, and view each shot separately.

### 4.2 Input

```python
ctx.params["topic"]                    # already validated against your manifest
ctx.file("reference")                  # a `file` param: .path, .sha256, .name
ctx.secret("OPENROUTER_API_KEY")       # never logged, never written to records
ctx.dry_run                            # True when running with fake assets
```

Never hardcode a key in your workflow. Beyond the obvious, a hardcoded key bypasses the budget engine entirely, so the money spent through it is invisible to every cost display and every budget limit.

**Use `ctx.file()` rather than `ctx.params[…]` for `file` settings, and put its `.sha256` in your step inputs, never its `.path`.** The path contains the run identifier, so keying on it means the same reference video re-pays for everything on every run. Worse, keying on the *name* means a different video called `reference.mp4` silently hits the cache of the old one. The uploaded file is copied into the request folder and never modified, so its hash is a stable identity for exactly as long as it needs to be.

### 4.3 Reporting

```python
ctx.stage(3, 7, "Generating shots")
ctx.log("3 shots queued", level="info")
ctx.decision(kind="model", chosen="…", alternatives=["…"], reason="…")
```

`ctx.stage()` takes a position, a total, and a description. All three are yours to choose — SFVF imposes no fixed set of stages, because a composition workflow and a generation workflow genuinely have different shapes.

`ctx.decision()` records a choice in the video's audit trail. Record anything consequential: which model, which provider, which fallback, which visual style. When a video comes out wrong weeks later, this is what makes the reason findable rather than guessable.

You do not need to record costs. Every SDK function does that itself.

#### `ctx.forecast()` — telling the chassis what this run will cost

```python
ctx.forecast("higgsfield", credits=len(shots) * 12, note="60 shots × 12 credits")
```

SFVF estimates cost before a run by matching against previous runs with the same `affects_cost` settings. That works for a workflow whose price is determined by its settings, and not at all for one whose price is determined by how long the script turned out to be.

So once you know, say so. A forecast is a soft reservation: it does not block anything by itself, but it makes the projected total visible on the card and in Statistics, and in an `atomic` workflow it triggers an immediate budget check. That check is the entire point — a forecast made before the first clip is generated stops an underfunded episode at shot zero rather than at shot forty.

Forecasts are recorded next to actual spend, so how wrong they were is measurable and therefore fixable.

### 4.4 Instructions

```python
ctx.rules(agent="scriptwriter")   # -> list of file paths, frozen for this run
ctx.skill("hook-writing")         # -> a file path
```

Pass the paths to your agents rather than reading the files and pasting their contents into the prompt. The agent then reads what it actually needs, and you are not paying for the whole instruction library on every call.

### 4.5 Running work

```python
with ctx.step("write-script",
              inputs={"topic": t, "duration": d},
              label="Script") as step:
    if step.cached:
        script = step.value
    else:
        script = expensive_thing()
        step.set(script)
```

Or, equivalently, as a decorator:

```python
@ctx.step("write-script")
def write_script(topic: str, duration: int) -> dict:
    ...
```

The first argument is the **family**, `inputs` is the **cache key**, `label` is **display only**. §5.2 explains why these are three separate things rather than one name.

`ctx.check_cancelled()` exists for long loops that do not cross a step boundary, so a stop request is still noticed.

### 4.6 Pausing for a decision

```python
decision = ctx.gate("approve-script", prompt="Approve before generation begins.",
                    payload={"script": script})
# -> {"choice": "approve"}
```

Execution stops until the user answers in the interface.

**Place gates before expensive stages, never after.** The purpose of a gate is to stop money being spent on a bad foundation. A gate placed after generation shows you the receipt; a gate placed before it prevents the charge.

#### Three shapes

| Shape | What you pass | What you get back |
|---|---|---|
| Approval | `prompt`, optional `payload` | `{"choice": "approve" \| "reject"}` |
| Choice | `options=["…", "…"]` | `{"choice": "<option>"}` |
| Selection | `items=[…]`, `select="subset"` | `{"choice", "keep", "redo", "note"}` |

The selection shape exists because "approve or abandon" is not the decision you actually want to make when looking at eight character sheets of which one is wrong:

```python
decision = ctx.gate(
    "approve-sheets",
    prompt="Approve the reference sheets before shot generation begins.",
    items=[{"id": "bertie", "label": "Bertie — turnaround",
            "artifact": "artifacts/sheets/bertie.png"},
           {"id": "clementine", "label": "Clementine — turnaround",
            "artifact": "artifacts/sheets/clementine.png"}],
    select="subset",
    on_bypass="approve-all",
)
# -> {"choice": "approve", "keep": ["bertie"],
#     "redo": ["clementine"], "note": "hood reads brown at small sizes"}
```

`items[].artifact` is a path relative to your video folder — write the image into `ctx.artifacts` first. Reference the file rather than embedding it: the gate event is appended to `events.jsonl`, which is also the replay input, and inlining images would bloat it for no gain.

#### `on_bypass`

A scheduled run may be configured to pass gates without pausing, since nobody is present to answer. `on_bypass` is what the gate returns in that case, and it is **mandatory for any gate that can return more than plain approval**. The chassis will not invent a default, because an invented default here means unattended regeneration nobody asked for.

#### Rejection

`{"choice": "reject"}` raises `GateRejected` in your code. Uncaught, the video fails, and the gate name and note are recorded. You may catch it to finish cleanly, but you may not catch it and return a video anyway — see §3.4.

#### The part that is easy to get wrong

If a gate tells you to redo something, the regenerating step must not return the cached original. It will, unless you say otherwise, because its inputs have not changed. Carry the attempt counter:

```python
attempt = ctx.gate_attempts("approve-sheets", item="clementine")   # 0, 1, 2 …

with ctx.step("character-sheet",
              inputs={"character": "clementine", "prompt": p,
                      "model": m, "attempt": attempt},
              label="Sheet — Clementine") as step:
    ...
```

`ctx.gate_attempts()` is derived from this video's recorded gate decisions, so it survives a resume. Omit it and the redo silently no-ops, which looks exactly like the model ignoring your feedback and takes a long time to recognise as a caching problem.

### 4.7 `ctx.map()` — many steps of one family, in parallel

An episode with sixty independent shots should not take sixty times one shot's wall clock. The concurrency setting controls how many *videos* run at once, which does nothing for a workflow producing one video made of sixty pieces.

```python
outcomes = ctx.map(
    "generate-shot", shots,
    inputs=lambda s: {"shot": s.spec, "refs": refs[s.id], "model": m},
    label=lambda s: f"Shot {s.index} — {s.slug}",
    fn=lambda s: media.video.generate(prompt_for(s), model=m, refs=refs[s.id]),
    concurrency=ctx.step_concurrency,
    on_error="collect",
)
```

**Every item is a full step.** Same family, its own cache key, its own record entry, its own retry budget. `ctx.map` schedules steps; it is not a new kind of unit with its own rules.

**Results come back in input order**, whatever order they finished in, so the editing code that follows needs no sorting.

**`on_error`** is `"raise"` by default, which propagates the first failure and fails the video, exactly as a sequential loop would. `"collect"` instead returns an outcome per item carrying either a value or an error, so a run with three bad shots can regenerate three shots rather than dying. If you use `"collect"`, you must still decide — and must still raise if what you have is not usable. §3.4 applies unchanged.

**Cancellation** is honoured between item completions; work already in flight finishes and saves, for the same reason a step does.

Pass `ctx.step_concurrency` rather than a number of your own. It is a user setting, it defaults to 1, and the per-provider rate limiter remains the real bound on how fast requests actually leave the machine.

---

## 5. Steps — the most important section in this document

A step is a unit of work whose result the chassis remembers. Wrap **every** meaningful unit of work in one.

### 5.1 What a step boundary does for you

Three things happen at a step boundary and nowhere else:

1. **The cache is consulted.** If this exact work has been done before, the previous result is returned instantly and nothing is executed or paid for.
2. **Progress and cost are recorded** against the step, so the video's record shows what took how long and what was reused.
3. **Cancellation is honoured.** A stop request is noticed here, allowing the current step to finish and save before the process exits.

Code written outside any step receives none of these. It will re-execute on every resume, it will not appear in the record, and it will not notice a stop request.

### 5.2 Family, inputs, label — three jobs, three fields

```python
ctx.step("generate-shot",                              # family
         inputs={"shot": spec, "refs": ids, "model": m},  # cache key
         label="Shot 4 — kitchen, wide")               # display
```

| Field | What it identifies | What matches on it |
|---|---|---|
| family | the *kind* of work | recovery options, time limits, statistics, estimation |
| `inputs` | this *particular* piece of work | the cache, and nothing else |
| `label` | nothing | shown in the interface and the record |

**Repeating a family within one video is normal.** Sixty shots are sixty steps all called `generate-shot`, distinguished by their inputs. This is deliberate. The obvious alternative — giving each step a unique name, whether positional like `shot-04` or content-derived like `shot-9f2a1c` — breaks in one of two ways.

Positional names break on insertion: add a shot at the front and every subsequent name shifts by one, so every subsequent cache key changes, and you re-pay for fifty-nine shots that did not change. Unique content-derived names avoid that but leave nothing for `[[recovery]]`, `[[limits]]` or timing statistics to match on, and turn `video.json` into a list of hashes.

Splitting the roles fixes both. It also improves the statistics: "generate-shot averages 94 seconds across 340 instances" is a usable figure, where unique names would have given 340 populations of one.

**`label` must never affect anything.** Rewording it must not invalidate a single cached result, which is why it is not part of the key.

### 5.2a How caching decides whether it has seen this before

The chassis builds a key by hashing four things together: your workflow's version number, the step's family, the `inputs` you declared in a fixed canonical order, and — separately — the content of any file the inputs refer to. If a stored result exists under that key, it is returned and the body never runs.

**A `Path` appearing anywhere in `inputs` is hashed by its contents, not by its text.** You never have to remember this, and it removes an entire class of the failure §5.3 is about: two different files at the same path can never collide, and the same file at two different paths always hits.

### 5.3 The one rule that genuinely matters

> **A step's body must be a pure function of its declared `inputs`.** It must not read anything that can vary without also being listed in `inputs`.

This is the single way a workflow author can silently break resumption, and the resulting failures are extremely difficult to diagnose, because nothing errors — you simply get a stale result that looks plausible.

```python
# WRONG
# The model is used but not declared. Switch to a different model and the
# cache still matches on {topic}, so you get the OLD script back, generated
# by the OLD model, with no error and no indication anything is wrong.
with ctx.step("write-script", inputs={"topic": topic}) as step:
    script = llm(prompt, model=ctx.params["model"])

# RIGHT
# The model is part of the identity of this work, so it belongs in inputs.
with ctx.step("write-script",
              inputs={"topic": topic, "model": ctx.params["model"]}) as step:
    script = llm(prompt, model=ctx.params["model"])
```

The test to apply: *if I changed this value, would I want different output?* If yes, it belongs in `inputs`.

Increasing your workflow's `version` invalidates all of its cached results. This is why the version must be increased whenever behaviour changes — otherwise a rewritten step will happily return results produced by the code you just replaced.

Note that this does **not** invalidate the library. Bumping your version to fix a script prompt must not throw away forty euros of character sheets. §7.2 explains the asymmetry.

### 5.3a The library is never an implicit input

The rule above has one consequence sharp enough to state separately.

> **Do not call `ctx.library.find()` inside a step. Resolve to asset ids outside the step, and declare the ids inside it.**

A step body that searches the library depends on library state that is not in `inputs` — precisely the failure §5.3 exists to prevent. And you cannot fix it by declaring "the library" as an input, because then adding one unrelated asset would invalidate every cached shot you own.

```python
candidates = ctx.library.find(facets={"subject": "bertie"})     # outside any step

with ctx.step("pick-refs",
              inputs={"need": shot.reference_need,
                      "candidates": [a.descriptor_sha for a in candidates],
                      "model": M}) as step:
    chosen = step.value if step.cached else step.set(
        agents.llm(prompt_with(ctx.library.describe(candidates)),
                   agent="art-director", model=M, schema=REF_CHOICE))

with ctx.step("generate-shot",
              inputs={"shot": shot.spec, "refs": chosen, "model": V},
              label=f"Shot {shot.index}") as step:
    ...
```

**Selection steps key on descriptor hashes; generation steps key on asset ids.** The asymmetry is doing real work. A new candidate appearing, or a caveat being added to an existing one, should reconsider the choice — so descriptors are in the selection key. But annotating an asset must never invalidate shots that already used it — so descriptors are absent from the generation key, which sees only the blob id.

One consequence worth knowing before it surprises you: editing a caveat re-runs selections, which may choose differently, which may re-pay for shots. That is correct behaviour, and it is why annotation is a deliberate act rather than a casual one.

### 5.4 Choosing how big a step should be

Make each expensive, independently-repeatable unit its own step.

Generating six shots should be six steps, not one. If all six live inside a single step and the fourth comes out unusable, rerunning means regenerating all six — and on a paid video model that is money spent to reproduce five things that were already fine. Six steps of one family, which is what `ctx.map()` produces, is the shape you want.

The opposite error also exists: wrapping something trivial in a step adds bookkeeping for no benefit. The line is roughly whether the work costs money, takes noticeable time, or could fail on its own.

### 5.5 What a provided function hands you back

Everything a step can return has to survive the step cache, which stores results as JSON. That one constraint governs the shape of every value the provided functions give you:

- **A file comes back as a path string, relative to the video folder** — never an open file object or a `Path` you can call methods on. The function has already written the file into `ctx.artifacts`; what you receive is the string `"artifacts/narration.m4a"`. The cache stores that file by its contents and restores it into place when a cached result is used. So write files into `ctx.artifacts` and pass these relative strings onward; do not build a `Path` and return it.
- **A structured result comes back as a JSON dict, read by subscript.** `Source`, `Speech`, and the like are dictionaries, not objects: `speech["duration"]`, `source["title"]` — **not** `speech.duration`. They cannot be attribute-access objects because an attribute-access object cannot round-trip through the JSON cache; on a cache hit you would get a plain dict back and the attribute access would fail. Reading by subscript works identically whether the value was just produced or just restored from cache.

**The one exception is the `Result` your `run()` returns.** It is a value you *construct* — `Result(video=…, caption=…)` — and it is handed to the chassis directly, not stored as a step result, so it is a real object with fields, and `Result.video` is a genuine `Path`. Everything a *provided function* returns follows the two rules above; `Result` does not.

Because of the first rule, the `-> Path` annotations in §6 are a readability shorthand: read them as "a video-relative path string, per §5.5", not as an open `Path` object.

---

## 6. The provided functions

Everything the chassis makes available. Each one records its own cost, respects the budget, queues itself behind the provider's rate limit, and returns a free stub when running in dry-run mode.

### 6.1 `sfvf.agents` — language models and research

```python
llm(prompt, *, agent, model, schema=None, attach=None) -> str | dict
research(query) -> list[Source]
```

`agent` determines which rules are injected into the prompt. `schema` requests structured output, so you get back a dictionary of known shape rather than prose you have to parse.

Each `Source` from `research()` is a JSON dict, read by subscript — `source["title"]`, `source["url"]`, `source["snippet"]` — for the reason in §5.5 (the result is cached as JSON). A `schema` result from `llm()` is a dict you read the same way.

`attach` is a list of `Path`s — images, or video clips where the model supports them — shown to the model alongside the prompt. This is how a shot gets described from reference footage, and how a generated frame gets checked against the character sheet it was supposed to match. Requires the `agents.vision` capability; declare it in your manifest. Not every model accepts attachments, and one that does not will fail rather than silently ignoring them.

When you attach files, remember that the step wrapping the call must key on those files. Putting the `Path` in `inputs` is enough — §5.2a hashes it by content for you.

`research()` results are cached by content, so running the same query again — including in a later run on a different day — costs nothing. **That is wrong for anything where recency is the point.** "The Krebs cycle" is the same query in November as in March; "the most interesting current development in fusion" is not, and will cheerfully hand you a cached answer from eight months ago. Put a coarse time bucket in the step's inputs so the staleness is a decision rather than an accident:

```python
with ctx.step("research", inputs={"topic": topic,
                                  "as_of": date.today().isoformat()}) as step:
```

**Always name a specific model.** OpenRouter can route automatically to whatever is available, but doing so means the video's record cannot say which model produced it, and the run cannot be reproduced. The pinned identifier is what ends up in the record.

### 6.2 `sfvf.media.image` — still images

```python
generate(prompt, *, model, refs=None, size=None) -> Path
edit(image, prompt, *, model, refs=None) -> Path
```

Character turnarounds, location plates, style references, and the first frames you chain clips from. Requires the `image.generate` capability.

Which provider backs this is an adapter decision and may change; your code should not care. Costs are reported in whatever unit that provider uses.

### 6.3 `sfvf.media.video` — Higgsfield

```python
generate(prompt, *, model,
         first_frame=None, last_frame=None,
         refs=None, duration_s=None, extra=None) -> Path
```

Handles the entire awkward part: submitting the job, polling until it finishes, timing out sensibly, retrying, and downloading the result. This is the single most tedious thing to reimplement and the most common source of silent failure, which is why it lives in the chassis. It also heartbeats while polling, which is what keeps a legitimately slow job from being killed by its time limit (§2.8).

`refs` conditions the generation on existing material:

```python
refs=[Ref(kind="character", path=sheet),
      Ref(kind="motion",    path=source_shot)]
```

`kind` is one of `character`, `style`, `motion`, `video`. Requires the `video.refs` capability, and not every model supports every kind — the adapter reports what it can do, and an unsupported combination fails at the call rather than quietly generating something unconditioned.

`extra` is a raw passthrough of model-specific arguments, recorded verbatim in the decision log. It exists because Higgsfield's tool surface is expected to move and its own client fetches the schema at run time rather than hard-coding it, so waiting for an SDK release to use a new argument would be the wrong trade. The cost is that a call using `extra` is not portable to another provider. Make that trade knowingly, and record why with `ctx.decision()`.

Clips are capped at roughly fifteen seconds. Build longer sequences by chaining, using `media.analyze.frame(clip, -1)` as the next clip's `first_frame`, which keeps the visual continuous across the join.

Costs are in credits rather than currency.

### 6.3a Reproducing an existing shot's timing

When you are regenerating reference footage one-to-one, the source is the timing authority and everything downstream depends on it. Generators produce in fixed duration buckets, so the recommended handling is:

1. Generate at the **nearest bucket at or above** the source duration.
2. **Trim the tail** to the source duration exactly. Tail rather than head, because generated clips usually establish well and drift late.
3. If the excess is more than about **20%** of the source, do not trim — a clip asked to fill much less time than it was made for reads as a held frame. Regenerate at a shorter bucket, or split the source shot at an internal cut and generate two.
4. **Never retime audio** to fit picture.

All four are deterministic and cache normally. The 20% figure is a starting point to revise from what you observe; it lives in your workflow because different source material wants a different number.

### 6.4 `sfvf.media.speech` — ElevenLabs

```python
speak(text, *, voice, model) -> Speech        # a JSON dict, read by subscript (§5.5)
# speech["audio"]    -> a video-relative path string to the audio file
# speech["timings"]  -> list of word timings, each {"word", "start", "end"}
# speech["duration"] -> the real length of the audio, in seconds
```

Always returns word-level timings alongside the audio. What ElevenLabs actually returns is *character*-level alignment, a start and end time for every character; the chassis groups those into words before handing them to you, so `timings` is a list of words either way. Caption synchronisation depends entirely on knowing when each word is spoken, so any backend that cannot supply alignment at all has it performed separately rather than returning without it. Your code never has to know which situation it is in.

`speech["duration"]` is the real length of the generated audio. **Do not cut narration to a target length.** A duration setting is guidance for the agent writing the script, not a cap on the speech; render and edit to `speech["duration"]` rather than to the number the user typed, as the worked example in §11 does. A workflow that truncates its own narration to hit a target produces a video that stops mid-sentence and still passes every automatic check.

The voice and model identifiers are recorded automatically. Without that, changing a default voice would quietly make every earlier run unreproducible.

#### Several speakers

`speak()` is per utterance, so a scene of dialogue is one call per line, each with its own voice, assembled with `media.edit`. Wrap each line in its own step for the usual reason: one bad line should not cost you the scene.

#### Where character voices come from

**The SDK does not create voices.** Voice design is done by hand in the ElevenLabs interface, and your workflow keeps the resulting identifiers in its own config file:

```toml
# workflows/fruit-drama/cast.toml
[bertie]
voice_id = "…"
notes    = "warm, slightly adenoidal"
```

This looks like an omission and is a deliberate refusal. A voice-creation call makes durable state in an external account that no step result represents: lose the record of it and an orphan voice exists that SFVF cannot see, cannot attribute cost to, and cannot clean up. It also has no sensible cache semantics, since the same inputs do not produce the same voice. A hand-edited file costs some copying and cannot leak.

A narrator voice chosen per run is a different thing and belongs in the Run pop-up as a `select` with `options_from = "elevenlabs.voices"`.

### 6.5 `sfvf.media.graphics` — HyperFrames

```python
render(composition_html, *, duration_s) -> Path
captions(audio, timings, style) -> Path
safe_zone_css() -> Path
check(composition_html, *, safe_zone=True) -> list[Violation]
```

HyperFrames renders are deterministic: the same HTML always produces the same video. That means they cache perfectly and cost nothing but processing time, so iterating on a composition is effectively free.

**Two rules your compositions must follow, because breaking them fails silently.** Do not read the real-world clock, and do not use randomness without a fixed seed. The renderer draws frames by asking the page what it looks like at a given moment, and it expects the same answer every time it asks about the same moment. A composition that consults the clock or rolls fresh random numbers gives different answers, and the resulting video is subtly wrong with no error message anywhere.

Import `safe_zone_css()` rather than writing margin values by hand. The platform's interface covers parts of the frame, and the correct margins live in one place so that a change updates every workflow at once. What it returns follows your `[output]` declaration, so a 16:9 workflow with `safe_zone = "none"` gets no margins rather than margins for a platform it will never be posted to.

#### `check()` — the failures that render perfectly

A composition written by an agent fails in ways no frame-sampling check catches: a chart positioned off-screen, a heading clipped mid-word, text under the platform's own buttons, a font that did not load so every glyph is an empty box. The video encodes cleanly, the frames are not black, the audio is fine, and the result is unusable.

`check()` loads the page once, headless, and inspects the DOM:

| Check | How |
|---|---|
| Element outside the viewport | bounding box against the viewport |
| Element intersecting the safe zone | bounding box against `safe_zone_css()` margins |
| Truncated text | `scrollWidth`/`scrollHeight` exceeding the client box |
| Missing font | text nodes rendering at fallback metrics |

No AI, deterministic, and effectively free. `finalize()` runs it automatically whenever a composition render is among its inputs, and violations fail the video rather than warning — a chart drawn off-screen is not a borderline case. Call it yourself while iterating, before spending anything on narration.

### 6.6 `sfvf.media.edit` — Kinocut

```python
cut(clips, *, transitions=None) -> Path
mix(tracks, *, duck=None) -> Path
trim(video, start, end) -> Path
```

These wrap Kinocut's programmatic interface, which is deterministic and therefore cacheable.

Kinocut also has an MCP interface, which lets an AI agent decide the edit itself. That is available to you, and it comes with a real cost: an agent-driven edit produces different results each time, so it cannot be cached or reliably resumed. Reach for it only when that flexibility is genuinely the point of your workflow.

`duck` refers to automatically lowering music volume while narration is speaking.

### 6.7 `sfvf.media.analyze`

```python
scenes(video) -> list[Shot]     # via PySceneDetect — where each shot starts and ends
probe(path)  -> MediaInfo       # duration, resolution, codec, audio levels
frame(video, at) -> Path        # a still; `at` in seconds, or -1 for the last frame
```

`frame()` is what makes clip chaining possible: take the last frame of one clip, hand it to the next as `first_frame`. Deterministic and free.

### 6.8 `sfvf.media.music` — Epidemic Sound

```python
find(mood, duration_s) -> Track
```

Licence details are recorded against the video automatically, so that if a claim is ever raised the record shows which track was used under which licence.

### 6.9 `sfvf.finalize` — required as your last step

```python
finalize(video, audio=None, captions=None) -> Path
```

Applies the codec, frame rate, resolution and loudness for the format you declared in `[output]`, then runs the automatic self-review: checking the file is valid, sampling frames to catch black or broken output, measuring audio for silence and clipping, confirming captions are present if expected, running the composition checks of §6.5 if a render was involved, and detecting whether the result is effectively a slideshow when motion was intended — against a threshold calibrated for your format, so a slow establishing shot in a long episode is not mistaken for a still.

Every workflow must end with this call. It is what guarantees that output is consistent regardless of what happened inside, and it catches the failure modes that a person would otherwise only find by watching the finished video.

---

## 7. The library — assets that outlive a run

Some things you generate are worth keeping for a year: a character's turnaround sheet, a location's reference views, a style plate every episode is matched against. They cost real money, they are made once, and they are referred to by what they *are* rather than by what produced them.

None of the existing places can hold them. `runs/` belongs to one Generation Request. `workflows/` is read-only while running. And the cache — which is the near miss — is keyed on your workflow's version, so bumping the version to fix a prompt would silently orphan every sheet you own, quite apart from the fact that cache entries are derived data that may be deleted at any time.

So the library is a fourth thing.

```
library/<namespace>/
├─ items/<sha256>          # the file
├─ items/<sha256>.json     # its descriptor — authoritative
├─ aliases.json            # name -> id, mutable
└─ catalog.json            # derived index; rebuildable by rescanning items/
```

### 7.1 What identifies an asset

**The content hash, and nothing else.** That is what goes in the record, what a step declares in its inputs, and what makes "which Bertie was in episode 7" answerable.

A **name is a handle**: a mutable pointer to an id, kept in `aliases.json`. `char/bertie/canonical` resolves to whichever sheet is current, and every resolution is recorded with the id it actually produced. So episode 12 asks for "the current Bertie" and the record still says exactly which one that was.

Names alone are not enough, which is why the rest of this section exists. Real bodies of work accumulate near-variants — Bertie in the raincoat, Bertie post-timeskip, Bertie's expression sheet — and a naming scheme that tries to encode all of that becomes a filing system nobody can query.

### 7.2 Why the library ignores your version number

Library keys deliberately do not include `version`. This is the exact inverse of the cache rule in §5.3, and it is right for the same reason that rule is right: you *want* a rewritten step to regenerate a cached script, and you emphatically do not want it to regenerate forty euros of character art because you fixed a typo in a prompt.

Nothing in the library is ever evicted automatically.

### 7.3 The descriptor

Each asset has a sidecar. The sidecar is authoritative; `catalog.json` is an index that can be thrown away and rebuilt.

```json
{
  "id": "9f2a…",
  "kind": "image",
  "created_utc": "…",
  "status": "active",
  "supersedes": "1c88…",

  "tags": ["character", "turnaround"],
  "facets": {"subject": "bertie", "view": "turnaround-8pt",
             "outfit": "raincoat", "era": "post-timeskip"},

  "description": "Full-body eight-point turnaround of Bertie…",
  "caveats": "Left hand malformed in the three-quarter rear view. Hood reads brown at small sizes.",

  "provenance": {"run_id": "…", "step": "…", "model": "…", "prompt": "…",
                 "derived_from": ["<sha256>"], "cost": {"higgsfield": 12}}
}
```

**Facets and description are not redundant, and the split is a cost mechanism.** Once you own three hundred assets you cannot put every written description into a prompt. Facets narrow the field deterministically and for free; prose then discriminates among the five survivors. Selection therefore stays a text operation, which is the entire point — looking at every candidate with a vision model, every time, would make reuse more expensive than regeneration.

**`caveats` earns its own field** because it is the part you can only write *after* using an asset, and it is the part that actually prevents the same mistake twice.

**`tags` and `facets` mean nothing to the chassis.** It filters on exact matches and has no idea what a character or an outfit is. This is what keeps the plug-in boundary where it is: the moment the chassis understands your subject matter, every new kind of video needs a chassis change.

### 7.4 Declaring your facets, and why you must

An agent writes `{"outfit": "raincoat"}` in one episode and `{"clothing": "rain-coat"}` in the next. `find()` returns nothing, your workflow concludes the asset does not exist, and regenerates something you already own. No error, real money, and now two near-identical assets compete for selection.

So facet keys are declared in the manifest and `put()` rejects undeclared ones (§2). Values are open or closed per key; a closed key cannot drift at all. Open values are normalised on write — lowercased, trimmed, spaces to hyphens — so `"Rain Coat"` and `"rain coat"` converge mechanically.

Beyond that the chassis **announces rather than corrects**. The first time an open key sees a new value, the run emits a `library` event and the catalogue entry is marked novel, so it surfaces in the record. Automatic merging by similarity is deliberately not done: a system that quietly decides `sou-wester` means `raincoat` will eventually be wrong in a way nobody can see, and that costs more than an occasional duplicate.

Schema changes behave predictably. Adding a key later leaves existing assets without it, and an absent facet does not match a query for that facet. Removing a key leaves it on existing assets and rejects it on new ones — tolerant read, strict write. Narrowing an open key to a closed set is refused while assets hold values outside it, which is one of the few places where refusing to load is better than half-enforcing.

### 7.5 The functions

```python
ctx.library.find(tags=…, facets=…, status="active") -> list[Asset]
ctx.library.get(name_or_id)                         -> Asset | None
ctx.library.put(name, path, *, tags, facets, description, caveats, meta) -> Asset
ctx.library.describe(assets)                        -> str    # compact text for a prompt
ctx.library.value(name)                             -> JSON   # small data, not a file
ctx.library.annotate(id, *, caveats=…, facets=…)    -> Asset
```

`find()` is deterministic, free, and pure — and must be called **outside** any step, for the reason set out in §5.3a.

`describe()` hands you text. It does not choose for you. Selection is `agents.llm()` with your own rules about what "matching" means for your kind of video, because the chassis has no opinion about which raincoat is correct.

**Write in `prepare()`, not in `run()`.** Videos within a request may execute concurrently. Writes are atomic — file written, then renamed — so a crash cannot produce a half-asset, but two `run()` calls provisioning the same character is still a race you should not be having.

**Pay for vision exactly once, at intake.** A description written from the prompt you used is a description of what you *asked for*, and generation drifts. So when an asset enters the library, run one vision pass over the artefact itself (`agents.llm(attach=[path])`) and write the description and initial caveats from what is actually there. That is one paid look per asset, ever; every selection afterwards, across every future episode, is free text.

### 7.6 State that is not a file

`value()` and `put()` accept small JSON as well as files, which is where series state belongs:

```python
state = ctx.library.value("series/state") or {"episode": 0, "threads": []}
```

`ctx.previous` only spans one Generation Request. If each episode is its own request — which it should be, for anything expensive — this is how episode 8 knows what happened in episode 7.

### 7.7 Supersession, not overwriting

Assets are never replaced in place. A redesigned character is a **new** asset whose descriptor names what it `supersedes`; the old one flips to `status: "superseded"`. `find(status="active")` skips it, and episodes 1–7 still resolve the ids they recorded.

`status: "rejected"` is the third case: something you generated, judged bad, and want to keep so the same mistake is not made again and the learning process can see it.

Deletion is a manual act in the interface, not something your code can do, and it writes a tombstone rather than removing anything referenced by a past run. An id in an old record is the only thing that makes a year-old video explicable; a dangling reference and a falsified record are both worse than a file that stays on disk.

### 7.8 Sharing a library between workflows

`namespace` defaults to your workflow id. Set it explicitly when two workflows are working on the same body of material — a shorts workflow and a longform workflow with one cast. Copying assets between namespaces is not the answer, since a copy has a different id and the records diverge.

### 7.9 In dry run

Reads hit the real library; writes go to an overlay that is discarded when the run ends. So a dry run of episode 8 genuinely rehearses *seven characters found, one missing, generate that one, use all eight* — the branch you most want to test for free — and leaves nothing behind.

One limitation, stated so it is not mistaken for a bug: the intake vision pass returns a stub in dry run, so your selection agent is reasoning over placeholder descriptions. A dry run rehearses the **shape** of selection, not its judgement.

---

## 8. Rules, skills and criteria

### 8.1 Rules

Short. Always included in the prompt of the agents they target.

```markdown
---
agents: [scriptwriter, hook-writer]
version: 2
---
Never open with a rhetorical question.
State the payoff within the first sentence.
```

A file with no `agents` line applies to all agents. Global rules and your workflow's rules are **combined, not overridden** — yours are added to the global ones rather than replacing them. Making sure they do not contradict each other is your responsibility, because any automatic conflict-resolution rule would be wrong about half the time and would hide the problem instead of showing it.

### 8.2 Skills

Longer. Referenced by path through `ctx.skill(name)` and read by the agent only when needed. Use them for material an agent needs occasionally rather than always: composition patterns, animation recipes, worked examples, style references.

The distinction from rules is about cost. Rules are paid for on every single call, so they must stay short. Skills are paid for only when read.

### 8.3 Criteria

Files in `criteria/` describing what a good video looks like for this workflow, split by concern rather than kept as one long document. They are read by the learning process, not by the agents that produce videos.

### 8.4 Freezing

At the start of every Generation Request, every rule and skill file that applies is copied into that run's folder and recorded with its content hash and version. Editing a rule next week therefore cannot change what a past run reports having used, and the interface can show the exact text that was in force when a given video was made.

---

## 9. Quality factors

Declared in your manifest. After a Generation Request finishes, the user writes a free-text answer to each factor for every video, then ranks that request's videos against one another for each factor. Accept or reject is recorded separately. **There are no numeric ratings.**

Write factors as specific, answerable questions.

- Good: *"Did the visuals stay consistent across shots? Where did they drift?"*
- Bad: *"Was it good?"*

The difference matters because these answers are the raw material for the learning process. A specific question produces an answer that names a problem; a vague one produces an adjective that cannot be acted on.

Rankings are relative and within a single Generation Request. Learning value therefore scales with how many videos each request produces — a request producing one video yields answers but no ranking, since there is nothing to compare against.

This bites hardest on `sequence` workflows, which produce one episode per request by design and so never rank at all. Write their factors accordingly: an answer that names a specific failure is the whole of the signal, so a question like *"Where did the character design drift, and in which shots?"* is worth far more here than one that only makes sense compared against an alternative.

---

## 10. Dry-run mode

When `ctx.dry_run` is true, every SDK function returns a free stub instead of calling a paid service: silent audio of a plausible length with invented timings, a colour-bar video of the requested duration, placeholder script text, canned research results. Cost recording still happens using estimated figures, so the run reports what it *would* have cost.

These stubs are generated on demand and written into `ctx.artifacts`, in the same place the real assets would have gone. There is no shared library of placeholder files, because almost every stub depends on something that varies: the audio has to match the length of the script standing in for it, the clip has to match the duration you asked for. A fixed file could not do that.

If your workflow needs a stub that has to be real content rather than a plausible shape, such as a reference video for a workflow whose whole input is reference footage, put it in your own `stubs/` folder and read it from `ctx.workflow_dir`. Keep it there rather than proposing a shared one: a reference clip chosen for your workflow is not useful to anyone else's.

**The library is not stubbed out.** Reads hit the real one, so the reuse path is exercised; writes go to a per-run overlay that is discarded, so nothing is polluted. See §7.9, including the one thing this cannot rehearse.

Use this constantly while developing. It is the difference between iterating on the structure of a pipeline for nothing and paying real money to discover a typo in a variable name.

---

## 11. Worked examples, with commentary

Two, because the two shapes stress different parts of this document. The first is composition-based and stateless; the second is asset-heavy, serial and expensive.

### 11.1 A researched explainer

```python
from datetime import date
from sfvf import Context, Result, agents, media


def prepare(ctx: Context) -> dict:
    # Runs once for the whole Generation Request. Every video shares
    # the topic and the research, so both belong here rather than in run().
    topic = ctx.params.get("topic")

    with ctx.step("choose-topic", inputs={"given": topic}) as step:
        if step.cached:
            topic = step.value
        elif not topic:
            # The user left the topic empty, so the agent picks one.
            topic = agents.llm("Pick one current topic worth explaining…",
                               agent="researcher", model="…")
            step.set(topic)
        else:
            step.set(topic)

    # as_of buckets the cache by day. Without it, "the most interesting
    # current development in X" would return an eight-month-old answer
    # for free and look like it had just been researched.
    with ctx.step("research", inputs={"topic": topic,
                                      "as_of": date.today().isoformat()}) as step:
        sources = step.value if step.cached else step.set(agents.research(topic))

    return {"topic": topic, "sources": sources}


def run(ctx: Context) -> Result:
    topic = ctx.shared["topic"]
    total = 5

    ctx.stage(1, total, "Writing script")
    # video_index is in the inputs on purpose: each video should get a
    # DIFFERENT script on the same topic. Without it, all five videos
    # would share one cached script.
    with ctx.step("script", inputs={"topic": topic,
                                    "variant": ctx.video_index,
                                    "duration": ctx.params["duration_s"]}) as step:
        script = step.value if step.cached else step.set(
            agents.llm(f"Write a {ctx.params['duration_s']}-second script on {topic}…",
                       agent="scriptwriter", model="…"))

    # The gate sits here, before anything is paid for. Approving a bad
    # script after the narration and render would be reviewing a receipt.
    # Plain approval, so no on_bypass is required.
    ctx.gate("approve-script", prompt="Approve the script.",
             payload={"script": script})

    ctx.stage(2, total, "Narration")
    with ctx.step("speech", inputs={"script": script,
                                    "voice": ctx.params["voice"]}) as step:
        speech = step.value if step.cached else step.set(
            media.speech.speak(script, voice=ctx.params["voice"], model="…"))

    ctx.stage(3, total, "Composition")
    # Building the HTML is cheap, so it happens outside a step. Rendering
    # it is not, so that goes inside one, keyed on the HTML itself —
    # identical HTML means an identical video, so the cache is exact.
    html = build_composition(script, speech["timings"], media.graphics.safe_zone_css())
    with ctx.step("render", inputs={"html": html}) as step:
        visual = step.value if step.cached else step.set(
            media.graphics.render(html, duration_s=speech["duration"]))

    ctx.stage(4, total, "Captions")
    captions = media.graphics.captions(speech["audio"], speech["timings"], style="bold")

    ctx.stage(5, total, "Finalising")
    # Mandatory. Applies the house format and runs the automatic checks.
    final = media.finalize(visual, audio=speech["audio"], captions=captions)

    return Result(video=final, caption=make_caption(script))
```

### 11.2 A serial episode built from reusable assets

Manifest: `video_semantics = "sequence"`, `max_videos = 1`, `atomic = true`,
`[output] aspect = "16:9"`, `safe_zone = "none"`.

```python
from sfvf import Context, Result, agents, media
from sfvf.media import Ref


def prepare(ctx: Context) -> dict:
    # Everything durable and expensive happens here. run() only spends.
    state = ctx.library.value("series/state") or {"episode": 0, "threads": []}
    episode = state["episode"] + 1

    with ctx.step("script", inputs={"episode": episode, "state": state,
                                    "model": SCRIPT_MODEL}) as step:
        script = step.value if step.cached else step.set(
            agents.llm(f"Write episode {episode}. Continuing threads: …",
                       agent="scriptwriter", model=SCRIPT_MODEL, schema=EPISODE))

    ctx.gate("approve-script", prompt="Approve before any art is generated.",
             payload={"script": script})

    # --- provision references ------------------------------------------------
    # find() is called OUT here, never inside a step (§5.3a).
    for name in script["cast"]:
        if ctx.library.find(facets={"subject": name, "view": "turnaround-8pt"},
                            status="active"):
            continue                                    # already own it, free

        attempt = ctx.gate_attempts("approve-sheets", item=name)
        with ctx.step("character-sheet",
                      inputs={"subject": name, "brief": script["cast"][name],
                              "model": IMAGE_MODEL, "attempt": attempt},
                      label=f"Sheet — {name}") as step:
            sheet = step.value if step.cached else step.set(
                media.image.generate(sheet_prompt(name), model=IMAGE_MODEL))

        # One paid look, ever. Every future selection reads this text for free.
        seen = agents.llm("Describe this sheet. Note any malformed detail.",
                          agent="asset-describer", model=VISION_MODEL,
                          attach=[sheet], schema=DESCRIPTOR)

        ctx.library.put(f"char/{name}/canonical", sheet,
                        tags=["character", "turnaround"],
                        facets={"subject": name, "view": "turnaround-8pt"},
                        description=seen["description"], caveats=seen["caveats"])

    # The selection gate: approve most, redo one, with a note explaining why.
    decision = ctx.gate("approve-sheets", prompt="Approve the reference art.",
                        items=[sheet_item(n) for n in script["cast"]],
                        select="subset", on_bypass="approve-all")

    # Now the shot count is known, so the run can be priced honestly — and an
    # atomic workflow that cannot afford it stops here rather than at shot 40.
    ctx.forecast("higgsfield", credits=len(script["shots"]) * CREDITS_PER_SHOT,
                 note=f"{len(script['shots'])} shots")

    return {"episode": episode, "script": script, "state": state}


def run(ctx: Context) -> Result:
    script = ctx.shared["script"]
    shots = script["shots"]
    ctx.stage(1, 3, "Selecting references")

    # Selection keys on DESCRIPTOR hashes: a new candidate or an added caveat
    # should reconsider the choice. Generation below keys on ASSET IDS, so
    # annotating a sheet never invalidates shots that already used it.
    refs = {}
    for shot in shots:
        candidates = ctx.library.find(facets={"subject": shot["subject"]})
        with ctx.step("pick-refs",
                      inputs={"need": shot["reference_need"],
                              "candidates": [a.descriptor_sha for a in candidates],
                              "model": DIRECTOR_MODEL},
                      label=f"Refs — shot {shot['index']}") as step:
            refs[shot["id"]] = step.value if step.cached else step.set(
                agents.llm(ref_prompt(shot, ctx.library.describe(candidates)),
                           agent="art-director", model=DIRECTOR_MODEL,
                           schema=REF_CHOICE))

    ctx.stage(2, 3, "Generating shots")
    # Sixty steps of ONE family: recovery, limits and statistics all match on
    # "generate-shot", while the cache distinguishes them by inputs.
    outcomes = ctx.map(
        "generate-shot", shots,
        inputs=lambda s: {"shot": s["spec"], "refs": refs[s["id"]],
                          "model": ctx.params["video_model"]},
        label=lambda s: f"Shot {s['index']} — {s['slug']}",
        fn=lambda s: media.video.generate(
            shot_prompt(s), model=ctx.params["video_model"],
            refs=[Ref(kind="character", path=ctx.library.get(i).path)
                  for i in refs[s["id"]]],
            duration_s=s["duration_s"]),
        concurrency=ctx.step_concurrency,
        on_error="collect")

    if any(o.failed for o in outcomes):
        raise RuntimeError(f"{sum(o.failed for o in outcomes)} shots unusable")

    ctx.stage(3, 3, "Assembly")
    lines = [speak_line(ctx, l) for l in script["dialogue"]]      # one step each
    final = media.finalize(media.edit.cut([o.value for o in outcomes]),
                           audio=media.edit.mix(lines))

    # Written back so the NEXT Generation Request can continue the story.
    # ctx.previous would not reach across requests; the library does.
    ctx.library.put("series/state",
                    value={"episode": ctx.shared["episode"],
                           "threads": script["threads_open"]})

    return Result(video=final, caption=script["logline"],
                  extra={"episode": ctx.shared["episode"]})
```

Four things in there are the whole point of this document. Reference art is looked for before it is made, so episode 9 pays for nothing episode 2 already bought. `find()` never appears inside a step. Selection and generation key on different things. And the forecast lands before the first paid clip rather than after the fortieth.

---

## 12. Checklist before shipping a workflow

- [ ] `id` matches the folder name and will never be changed.
- [ ] `version` increased for every change in behaviour.
- [ ] Every expensive unit of work sits inside its own `ctx.step()`.
- [ ] Every step declares **all** the varying values its body reads.
- [ ] Repeatable units such as individual shots are separate steps of one family, not one combined step and not sixty uniquely-named ones.
- [ ] `label` is never load-bearing; nothing breaks if you reword it.
- [ ] `ctx.library.find()` is never called inside a step.
- [ ] Selection steps key on descriptor hashes; generation steps key on asset ids.
- [ ] `file` parameters are read through `ctx.file()`, and keyed by `.sha256`.
- [ ] Every facet key the workflow writes is declared in the manifest.
- [ ] Library writes happen in `prepare()`, and every asset gets one vision pass at intake.
- [ ] Anything time-sensitive has a freshness bucket in its inputs.
- [ ] Gates are placed before expensive stages, not after them.
- [ ] Every gate that can return more than plain approval declares `on_bypass`.
- [ ] Regeneration after a gate carries `ctx.gate_attempts()` in its inputs.
- [ ] A forecast is emitted as soon as the run's size is known.
- [ ] `[[limits]]` covers any family that legitimately runs long.
- [ ] `affects_cost` is set on model, duration and count settings, and on no free-text field.
- [ ] Voice and model lists use `options_from`, not a hand-written `options` list.
- [ ] Nothing truncates narration to a target duration.
- [ ] Recovery options are declared for steps that can fail on a provider.
- [ ] Quality factors are specific questions, not yes/no.
- [ ] Compositions import `safe_zone_css()`, and use neither the real clock nor unseeded randomness.
- [ ] The workflow ends with `finalize()`.
- [ ] It runs cleanly from beginning to end in dry-run mode.

---

## 13. Common mistakes and what they cause

| Mistake | What actually happens |
|---|---|
| A step reads a value it did not declare in `inputs` | You get an old cached result that looks correct and is wrong, with no error anywhere. The hardest failure in this system to diagnose. |
| One step wrapping several shots | One unusable shot forces paid regeneration of all of them. |
| Work performed outside any step | It re-runs on every resume, never appears in the record, and ignores stop requests. |
| An API key written into the code | Bypasses the budget engine, so the spending is invisible to every limit and every display. |
| A gate placed after generation | You review the cost instead of preventing it. |
| Reading the clock or using unseeded randomness in a composition | The render is silently corrupted. No error is produced. |
| Skipping `finalize()` | Output does not conform to the standard format and none of the automatic checks run. |
| Catching an error and returning a broken video | The failure is counted as a success and gets ranked against good videos, poisoning the learning data. |
| `affects_cost = true` on a topic field | No two runs ever match, so cost estimates permanently fall back to a crude average. |
| A hand-written voice or model list in `options` | The user's own cloned voices never appear, and the list rots silently as the provider's catalogue moves. |
| Cutting narration to hit the duration setting | The video ends mid-sentence and passes every automatic check, because a truncated file is still a valid one. |
| `ctx.library.find()` called inside a step | The step depends on library state it did not declare. Same silent staleness as the first row, arriving months later when the library has grown. |
| Regenerating after a gate without `gate_attempts` | The cache returns the rejected original. It looks exactly like the model ignoring your feedback. |
| Keying a step on a file's path instead of its contents | Re-pays for everything every run, and a different file with the same name silently hits the old cache. |
| Writing a facet key that is not declared | Rejected at `put()` — which is the good case. The bad case is the near-miss spelling you never declared and never noticed. |
| Writing an asset description from the prompt rather than the artefact | You are describing what you asked for, not what you got. Every future selection is made on a plausible lie. |
| Library writes in `run()` rather than `prepare()` | Concurrent videos race to provision the same asset. |
| A gate with choices and no `on_bypass` | The scheduled run has nothing to answer with; the workflow blocks until someone notices, or the gate is refused at validation. |
| No forecast in an `atomic` workflow | Pre-flight can only guess from history, so an episode that cannot be afforded stops halfway instead of at the start. |
| Assuming `ctx.previous` spans Generation Requests | It is `None` at the start of every request. Series state belongs in the library. |
