# SFVF — Architecture Blueprint

**Version:** 2.3
**Companion to:** SFVF Product Requirement Document v2.3
**Purpose:** How to build it. The PRD says what SFVF should do; this document says how it should be constructed.

---

## 0. Glossary of implementation terms

Defined here so the rest of the document can use them freely.

**Backend.** The program that does the actual work — running workflows, tracking money, reading and writing files. It has no visual interface of its own.

**Frontend.** The visual interface, displayed in a web browser, which shows what the backend is doing and sends it instructions.

**FastAPI.** A Python library for building a backend that the frontend can talk to over ordinary web requests.

**Server-Sent Events (SSE).** A method by which the backend can push updates to the browser as they happen, without the browser having to repeatedly ask "has anything changed?". Used here for live progress, so that a running workflow's stage updates immediately.

**Process.** A running program, as the operating system sees it. Two processes have separate memory and cannot corrupt one another.

**Subprocess.** A process started by another process. SFVF starts one subprocess per video.

**Process tree.** A process together with every process it started, and everything those started in turn. Terminating a process tree kills the whole family, which matters because FFmpeg and headless browsers are started by workflows and would otherwise survive as orphans.

**stdout / stderr.** Two output channels every program has. `stdout` ("standard output") is where a program writes its normal output; `stderr` ("standard error") is where it writes error messages. SFVF reads both from each workflow subprocess.

**SIGTERM.** A polite signal sent by the operating system asking a process to shut down. The process can catch it and clean up first, which is what allows a graceful stop.

**Sentinel file.** An ordinary empty file used purely as a signal. Its presence means something. SFVF uses one to tell a running workflow that the user pressed stop, because a file is trivially visible to a separate process without any communication machinery.

**JSON.** A plain-text format for structured data, readable by both humans and programs.

**JSON Lines (JSONL).** A file or stream where each line is one complete, independent JSON object. Useful for streams of events, because a reader can process each line the moment it arrives rather than waiting for the whole thing to finish.

**Schema.** A description of what shape a piece of data must have — which fields exist, what type each one is, which are required. Used to validate manifests and settings before anything runs.

**Hash (SHA-256).** A function that turns any input into a fixed-length string of characters, where the same input always produces the same string and any change produces a completely different one. Used to detect whether something has changed, and to give cached results a name derived from their contents.

**Content-addressed.** A storage scheme where an item's name *is* the hash of its contents. Two identical items therefore automatically share one entry, and looking something up is the same operation as asking "have I seen exactly this before?".

**Canonical form.** A single agreed way of writing something that could be written several ways — for example, always sorting the keys of a data structure before hashing it. Without this, two identical sets of inputs written in a different order would produce different hashes and the cache would miss.

**LRU (Least Recently Used).** A rule for deciding what to delete when storage is full: discard whatever has gone longest without being used.

**Semantic versioning (semver).** A version-numbering convention of the form major.minor.patch, where the first number changes only when something breaks compatibility with what came before.

**Adapter.** A small module that translates between one external service's particular way of doing things and the single uniform interface the rest of the program expects. One adapter per provider means the rest of the code never has to know which provider it is talking to.

**Rate limit.** A cap imposed by a service on how many requests it will accept in a given period. Exceeding it produces rejections that look like random failures unless something is deliberately preventing it.

**HTTP range request.** A way of asking a web server for only part of a file. Video playback in a browser depends on it, because seeking to the middle of a video requires fetching the middle of the file rather than all of it.

**ffprobe.** A companion tool to FFmpeg that reports facts about a media file — duration, resolution, codec, audio levels — without modifying it.

**Staging area.** A separate location where proposed changes are written and held before anyone decides whether to apply them to the real files.

**Library.** A durable, named, described store of reusable assets belonging to a body of work rather than to any one run. Distinct from the cache in every property that matters: it is addressed by name and by structured metadata rather than by an opaque key, it is unaffected by workflow version changes, and nothing in it is ever evicted automatically.

**Descriptor.** The metadata file beside a library asset, holding its tags, facets, written description and known defects. It exists so that choosing between assets is a text operation rather than a paid visual one.

**Facet.** One declared structured metadata key on an asset. Workflows define their own; the chassis filters on them and understands nothing about what they mean.

**Step family.** The name given to a step, identifying the kind of work rather than one particular instance of it. Sixty shots are sixty steps of one family.

**Heartbeat.** A signal emitted by the SDK while it waits on an external service, telling the supervisor that the step is alive. Step time limits measure silence between heartbeats rather than elapsed time.

**Forecast.** A workflow's own statement of what the remainder of a run will cost, issued once it knows something the chassis could not have known in advance.

---

## 1. The stack, and why

### 1.1 The decision

**A Python backend serving a local web interface in the browser.** Not a packaged desktop application built with Tauri or Electron.

### 1.2 The reasoning, in full

The question is not really "web or desktop". Whatever is built, the core of it must be a long-running program that starts subprocesses, drives FFmpeg, manages isolated Python environments, and keeps working for the many minutes a video takes to produce. That program is server-shaped regardless of how it is presented. The only real question is what draws the interface on top of it.

The argument that decides it is a dependency argument. **SFVF creates isolated Python environments while it is running**, in order to install each workflow's own libraries. Creating those environments requires a real, ordinary Python interpreter present on the machine — not a frozen or bundled one, because a bundled interpreter cannot spawn new environments the way this design needs. FFmpeg must also be installed, and so must a headless Chromium browser for HyperFrames.

The entire purpose of desktop packaging is to produce a self-contained application that a user can install without installing anything else. That is impossible here, because three separate system-level dependencies must be present anyway. Choosing Tauri or Electron would therefore mean paying all of the packaging cost — a Rust toolchain or a bundled copy of Chromium that goes unused, sidecar process configuration, code signing, update mechanisms — while collecting almost none of the benefit.

There is also exactly one user, on one machine. Distribution is not a goal, which removes the remaining reason packaging usually exists.

The honest counterweight: a desktop application handles local video playback and "open this folder" more elegantly, and it removes the small daily friction of remembering to start the server. Those are real. They are outweighed by the dependency argument and by the fact that a browser-based interface can be wrapped in a desktop shell later, without changing anything beneath the presentation layer, if that friction becomes annoying enough to be worth solving.

### 1.3 Components

| Layer | Technology | Why |
|---|---|---|
| Backend | Python 3.12 with FastAPI | Python because every relevant library — AI clients, FFmpeg wrappers, PySceneDetect, Kinocut's client — is Python-first. FastAPI because it is small, well-documented, and AI coding assistants produce correct code for it reliably. |
| Live updates | Server-Sent Events | Simpler than a bidirectional connection, and the traffic is entirely one-directional: the backend reports progress, the frontend never streams anything back. |
| Frontend | Any modern framework | The state involved is simple enough that the choice does not affect anything else in this document. |
| Storage | JSON files on disk | See §1.4. |
| Scheduling | A timer inside the backend | The backend is already running continuously; adding an external scheduler would introduce a second thing that must also be running. |
| Video playback | A file-serving route supporting range requests | Range support is not optional. Without it, video plays from the start but cannot be seeked. |

### 1.4 Why there is no database

The filesystem is already the data model. The application's contents are folders of videos, folders of intermediate files, and markdown instruction documents. Adding a database would mean maintaining a second copy of facts that already exist as files, and every place where the two could disagree becomes a bug.

The access pattern also does not call for one. Records are small, are written once and read many times, and are naturally divided by run — nothing ever needs to query across all of them at once except the Statistics tab, which reads a bounded set of summary files.

If listing ever becomes slow because there are thousands of runs, the correct response is to add an index file that caches the summary information, not to introduce a database. The index can be rebuilt from the files at any time, which keeps the files authoritative.

---

## 2. Directory layout

```
sfvf/
├─ app/                          # the backend
│  ├─ api/                       # routes the frontend calls
│  ├─ core/                      # supervisor, scheduler, budget, secrets
│  ├─ registry/                  # finding and validating workflows
│  ├─ learning/                  # the SkillOpt integration
│  └─ web/                       # the built frontend files
│
├─ sdk/                          # the library installed into every workflow environment
│
├─ workflows/                    # THE PLUG-INS — never written to while running
│  └─ <workflow-id>/
│     ├─ workflow.toml           # the manifest
│     ├─ requirements.txt        # this workflow's library dependencies
│     ├─ main.py                 # the entry point
│     ├─ thumbnail.png
│     ├─ criteria/               # what "good" means, for the learning process
│     ├─ rules/                  # this workflow's agent instructions
│     ├─ skills/
│     └─ stubs/                  # optional; dry-run stand-ins this workflow needs
│
├─ rules/                        # global instructions — edited by hand only
├─ skills/
├─ assets/
│  └─ fonts/                     # bundled, openly-licensed fonts
│
├─ runs/                         # ALL OUTPUT LIVES HERE
│  └─ <workflow-id>/
│     └─ <run-id>/
│        ├─ request.json         # record of the Generation Request
│        ├─ events.jsonl         # everything that happened, with timestamps
│        ├─ instructions/        # frozen copies of the rules and skills used
│        ├─ shared/              # output of the shared preparation phase
│        ├─ 01/                  # the first video
│        │  ├─ video.json        # record of this video
│        │  ├─ final.mp4
│        │  ├─ .steps/           # saved results of completed steps
│        │  └─ artifacts/        # script, audio, shots, captions
│        └─ 02/ …
│
├─ cache/                        # DERIVED results reusable across runs
│  ├─ paid/                      # never deleted automatically
│  └─ cheap/                     # deleted oldest-first above a size limit
│
├─ library/                      # AUTHORED assets that outlive every run
│  └─ <namespace>/
│     ├─ items/<sha256>          # the asset itself
│     ├─ items/<sha256>.json     # its descriptor — authoritative
│     ├─ aliases.json            # name -> id, mutable
│     └─ catalog.json            # derived index; rebuildable from items/
│
├─ venvs/                        # one isolated environment per workflow
├─ archive/                      # previous versions of edited rules and skills
├─ schedules.json
├─ settings.json
└─ secrets.enc                   # encrypted keys and tokens
```

### 2.1 Why code and output are separated

Placing output inside each workflow's folder would seem natural, and it is wrong for four reasons. A workflow could not be copied, shared or version-controlled without dragging gigabytes of video with it. Deleting or reinstalling a workflow would destroy its entire history. A coding assistant pointed at the workflow folder to make changes would have hundreds of run folders in its field of view, wasting its attention and inviting it to modify things it should not. And code and output want completely different backup treatment — one is small and precious, the other large and reproducible.

### 2.1b Why the library is not the cache, and not in `workflows/`

Three properties of a character reference sheet make it fit none of the existing locations, and each one rules out a different candidate.

It is **not derived**. A cache entry can be deleted at any time and recomputed from its inputs; that is what makes eviction policies safe. A generated reference sheet cannot be recomputed, because the generation was not deterministic. Deleting it destroys something.

It is **not version-scoped**. Cache keys include the workflow's version number, deliberately, so that changing a step's behaviour invalidates its stored results. Applying that to assets would mean a typo fix in a prompt silently throwing away every sheet the workflow owns.

It is **written while running**, which rules out `workflows/`, where writing during a run is prohibited outright.

So it is a fourth top-level directory. Cache and library sit beside each other and are easily confused, so the distinction is worth keeping in one sentence: **the cache remembers work, the library holds things.**

`catalog.json` is an index and never authoritative, for the same reason given in §1.4 for run listings — the files are the truth and the index is a convenience that can be rebuilt whenever it is doubted.

### 2.1a Where dry-run stubs come from

There is deliberately **no shared stub library**. Most stubs are parametric rather than fixed: silent audio has to match the length of the script it stands in for, a colour-bar clip has to match the requested duration. A folder of static files could not satisfy that, so the chassis generates these on demand with FFmpeg and writes them into the video's own artifacts folder, exactly where the real assets would have gone.

The exception is a stub that has to be real content rather than a plausible shape. The planned animation-to-realism workflow takes a reference video as input, and no generated placeholder substitutes for one. Those belong in that workflow's own `stubs/` folder, because a reference clip chosen for one workflow is meaningless to another, and a shared folder would accumulate files nobody could safely delete.

### 2.2 Run identifiers

Format: `YYYYMMDD-hhmmss` in **UTC**, for example `20260810-143022`. If a second run somehow begins within the same second, a letter is appended — `20260810-143022A`, then `B`.

There are no spaces. This is not fussiness: shell commands generated by a coding assistant will eventually fail to quote a path, and a space is the character that turns that oversight into a broken command. UTC rather than local time avoids an hour of runs sharing timestamps with an hour of earlier runs when clocks change.

---

## 3. How runs execute

### 3.1 The process structure

```
Backend (runs continuously)
 │
 ├── Supervisor
 │     ├── preparation → subprocess (runs once for the whole request)
 │     ├── video 01    → subprocess ── worker threads (ctx.map, within the video)
 │     ├── video 02    → subprocess
 │     └── …              (how many at once = the request's concurrency setting,
 │                         or exactly one at a time under "sequence")
 │
 ├── Scheduler
 ├── Budget engine
 └── Event stream → the browser
```

**Only one Generation Request may be active per workflow at a time.** This is a deliberate simplification rather than a technical limitation. It makes the card's outline colour unambiguous, keeps budget accounting simple, and removes any possibility of two runs of the same workflow competing over the same cached results.

### 3.1a Two kinds of concurrency

The videos of a request run in parallel up to the request's concurrency setting. That is useless to a workflow producing one video composed of sixty independent generations, so there is a second, independent axis: **parallel steps within one video**, requested by the workflow through `ctx.map()` and bounded by its own per-request setting.

Both are bounded in turn by the per-provider rate limiter (§5.5), which remains the only thing that actually governs how fast requests leave the machine. Total in-flight work is the product of the two settings, which sounds alarming and is not, for that reason.

### 3.1b Sequential requests

A workflow declaring `video_semantics = "sequence"` is run one video at a time in index order, whatever the concurrency setting says, and a failure **cancels the videos after it** rather than letting them proceed. Both rules invert the defaults, and both follow from the same fact: episode 5 is built on episode 4's ending state, so running them together is impossible and running 5 after 4 failed produces nonsense.

The prior video's `Result.extra` is passed into the next video's `context.json` as `previous`. Continuity *between* Generation Requests is not handled here and is not supposed to be — that is what the library is for.

### 3.2 Starting a workflow subprocess

```
venvs/<workflow-id>/bin/python -m sfvf.runner \
    --workflow workflows/<workflow-id> \
    --context runs/<workflow-id>/<run-id>/01/context.json
```

The `context.json` file carries everything the workflow needs to begin: validated settings, all the paths it should use, the locations of the instruction files that apply, the secrets it is permitted to use, and the output of the shared preparation phase.

Passing this as a file rather than as command-line arguments avoids two problems: command lines have length limits, and secrets passed as arguments are visible to anything that can list running processes on the machine.

### 3.3 How a workflow reports back

The workflow writes **JSON Lines** to its standard output — one complete JSON object per line:

```json
{"t":"stage","index":3,"total":7,"label":"Generating shots"}
{"t":"log","level":"info","msg":"3 shots queued"}
{"t":"cost","meter":"higgsfield","unit":"credits","amount":12,"note":"shot 2"}
{"t":"cost","meter":"openrouter","unit":"EUR","amount":0.031,"note":"script"}
{"t":"forecast","meter":"higgsfield","unit":"credits","amount":720,"note":"60 shots"}
{"t":"step","name":"generate-shot","key":"9f2a1c","label":"Shot 4","status":"cached"}
{"t":"progress","family":"generate-shot","done":37,"total":60}
{"t":"heartbeat","name":"generate-shot","key":"9f2a1c","waiting_on":"higgsfield"}
{"t":"decision","kind":"model","chosen":"…","alternatives":["…"],"reason":"…"}
{"t":"artifact","path":"artifacts/script.md","label":"Script"}
{"t":"library","event":"put","id":"9f2a…","name":"char/bertie/canonical"}
{"t":"library","event":"novel-facet","key":"outfit","value":"sou-wester"}
{"t":"gate","name":"approve-sheets","select":"subset","on_bypass":"approve-all",
 "prompt":"Approve the reference art.",
 "items":[{"id":"bertie","label":"Bertie — turnaround",
           "artifact":"artifacts/sheets/bertie.png"}]}
{"t":"result","video":"final.mp4","caption":"…"}
```

Three of these deserve a note.

**`step` carries three fields where v2.2 carried one.** `name` is the step *family*, `key` is the truncated hash of its declared inputs, and `label` is for display. Sixty shots emit sixty events sharing one `name`; the pair of `name` and `key` is what identifies an instance. Everything that matches on steps — recovery options, per-family time limits, timing statistics, cost estimation — matches on `name` alone, which is the point of the split.

**`heartbeat` exists so that time limits can measure silence rather than elapsed time.** See §5.3.

**`gate` references artifacts by path rather than embedding them.** The backend already serves the video folder for the detail view, so an image-review gate needs no new transport, and `events.jsonl` — which is also the replay input — is not inflated by base64 images.

This format is chosen because it requires no network ports, no message-passing library, and no shared memory. A subprocess writing text to its own output is the simplest possible channel, and each line can be processed the moment it arrives.

**Any line that is not valid JSON is recorded as an ordinary log message rather than treated as an error.** This tolerance is deliberate and important. Workflows are written quickly; one will eventually print a debugging message, or include a library that writes its own progress bar to the output. Under a strict protocol that would break the run. Under this one it becomes a log line that appears in the record, which is exactly where you would want to see it anyway.

Everything received is appended to `events.jsonl` with a timestamp. That single file is the entire input to the replay view — no additional instrumentation is needed anywhere, because the events were already being recorded for live progress.

**The `total` on a `stage` event may change during a run, and the interface must tolerate it.** A workflow that detects shot boundaries in a reference video does not know how many stages it has until it has looked. Latching the first total received would render nonsense for exactly the workflows that need progress reporting most.

### 3.4 Stopping

A graceful stop writes a sentinel file into the video's folder and sends SIGTERM. The SDK checks for that file at every step boundary, so the step currently running completes and saves its result before the process exits. This matters because the running step has usually already been paid for.

A second stop terminates the whole process tree immediately. Killing the tree rather than just the main process is necessary because FFmpeg and headless browser processes are started by the workflow and would otherwise keep running invisibly, holding files open and consuming the machine.

### 3.5 Gates

When a workflow emits a `gate` event, it blocks, waiting for a **response file** to appear in the video's folder. The backend shows the gate in the interface; when the user decides, the backend writes the file and the workflow continues.

v2.2 used an empty sentinel whose mere presence meant "continue". It now carries the decision as JSON:

```json
{"choice": "approve", "keep": ["bertie"], "redo": ["clementine"],
 "note": "hood reads brown at small sizes"}
```

The property that mattered — surviving a backend restart while a workflow sits at a gate — is unaffected, because a file with contents survives exactly as well as an empty one.

**Three gate shapes** are distinguished by what the event declares. A gate with neither `options` nor `items` is plain approval and returns a `choice` of `approve` or `reject`. A gate with `options` returns the chosen one. A gate with `items` and `select: "subset"` returns which items to keep and which to redo, which is the shape needed to look at eight reference sheets and reject one.

`reject` raises inside the workflow rather than being reported as a chassis error, so the workflow decides whether to fail or to finish cleanly.

**Bypass.** Scheduled runs configured to bypass gates have the response file written immediately, using the `on_bypass` value the gate declared. The chassis never invents a default for a gate that can return more than approval, because an invented default there means unattended regeneration nobody requested. A gate that needs `on_bypass` and does not declare it is a manifest-level authoring error and fails validation of the run rather than being guessed at.

**Gate durations** are recorded but excluded from step timing statistics, unchanged from v2.2: the elapsed time measures how long the person took to answer, not how long anything ran.

---

## 4. Stored data

Everything is JSON files. The structures below are indicative rather than exhaustive.

### 4.1 `request.json` — the record of a Generation Request

```json
{
  "run_id": "20260810-143022",
  "workflow": {"id": "news-explainer", "version": "1.3.0", "sdk": "1"},
  "started_utc": "2026-08-10T14:30:22Z",
  "ended_utc":   "2026-08-10T15:04:11Z",
  "status": "complete",
  "params": {"topic": "…", "duration_s": 45},
  "params_locked_utc": "2026-08-10T14:30:22Z",
  "budget": {
    "openrouter": {"unit": "EUR",        "limit": 2.00, "reserved": 0, "spent": 1.42},
    "higgsfield": {"unit": "credits",    "limit": 150,  "reserved": 0, "spent": 96},
    "elevenlabs": {"unit": "characters", "limit": null, "spent": 4210}
  },
  "forecast": {"higgsfield": {"unit": "credits", "amount": 720, "at_utc": "…"}},
  "videos": [{"index": 1, "status": "complete"}]
}
```

`params` is written once, when the request starts, and never modified afterwards. `params_locked_utc` records the moment it was fixed. The interface reads this file to render the read-only settings view offered from a running or paused card.

`status` may be `running`, `complete`, `partial`, `stopped`, `stopped-budget` or `failed`. `partial` means some videos succeeded and others did not, which under the statistical approach to failure is a normal outcome rather than an error.

**`partial` is not produced for a workflow declaring `atomic = true`.** For those, an incomplete video has no value, so a request that ends with one is `stopped`, `stopped-budget` or `failed`. Keeping `partial` to its original meaning matters because the Statistics tab and the learning module both treat it as a success with attrition, which a half-generated episode is not.

### 4.2 `video.json` — the record of one video

```json
{
  "index": 1,
  "status": "complete",
  "started_utc": "…", "ended_utc": "…",

  "cost": {
    "actual":   {"openrouter": 0.44, "higgsfield": 24},
    "uncached": {"openrouter": 0.44, "higgsfield": 48}
  },

  "steps": [
    {"name": "write-script", "key": "3d81aa", "label": "Script",
     "status": "ok", "cached": false, "seconds": 12.4},
    {"name": "generate-shot", "key": "9f2a1c", "label": "Shot 4 — kitchen, wide",
     "status": "ok", "cached": true, "seconds": 0.1}
  ],

  "instructions": {
    "scriptwriter": [
      {"path": "rules/tone.md", "sha256": "9f2a…", "version": 2, "scope": "global"},
      {"path": "workflows/news-explainer/rules/structure.md",
       "sha256": "1c88…", "version": 5, "scope": "workflow"}
    ]
  },

  "library": [
    {"id": "9f2a…", "alias": "char/bertie/canonical",
     "descriptor_sha": "77b0…", "used_by": ["generate-shot:9f2a1c"]}
  ],

  "gates": [
    {"name": "approve-sheets", "seconds": 412.0,
     "decision": {"choice": "approve", "keep": ["bertie"], "redo": ["clementine"],
                  "note": "hood reads brown at small sizes"},
     "bypassed": false}
  ],

  "decisions": [
    {"kind": "model", "chosen": "…", "alternatives": ["…"], "reason": "…"}
  ],

  "artifacts": [{"path": "artifacts/script.md", "label": "Script"}],

  "self_review": {"passed": true, "checks": {"black_frames": "ok", "audio": "ok"}},

  "result": {"video": "final.mp4", "caption": "…", "cover_frame_s": 1.0},

  "quality": {
    "verdict": "accepted",
    "answers": {"hook": "Opens on the number, works.", "coherence": "Drifts at shot 4."},
    "ranks":   {"hook": 1, "coherence": 3}
  },

  "error": null
}
```

Four details deserve explanation.

**Why cost is recorded twice.** `actual` is what was really spent. `uncached` is what the same work would have cost with nothing reused. Estimates for future runs use `uncached`, because a resumed run that reused six previously-computed steps might have spent almost nothing, and averaging that in would badly understate the price of starting fresh.

**Why instructions are recorded per agent.** When a video comes out wrong, the useful question is which instructions that particular agent was operating under. Recording a flat list of every file used would not answer it.

**Why library use is recorded with two hashes.** `id` is the asset's content hash and `descriptor_sha` is its metadata's. Both are needed and they answer different questions. When a character looks wrong in an old episode, `id` says which file was actually used — an alias like `char/bertie/canonical` is mutable and by now points somewhere else. `descriptor_sha` says what the selecting agent was told about it, which is the question when the *wrong* asset was chosen from a correct set. Recording only the alias would answer neither.

**Why gate decisions are recorded rather than just their timing.** A regeneration that a gate requested is indistinguishable, in the steps list, from one caused by a cache miss. The decision is what explains why a step ran twice, and `bypassed` distinguishes a person approving from a scheduled run passing the gate unattended — which matters when reviewing a video nobody watched being made.

---

## 5. The modules

### 5.1 Registry — finding and validating workflows

Scans for `workflows/*/workflow.toml`, validates each one against a schema, and reports problems per workflow rather than refusing to start the whole application. One broken plug-in should not prevent the others from being usable.

Validation checks that the identifier matches the folder name, that the declared entry point can actually be imported, that the settings schema is well-formed, and that the SDK version the workflow was written against is compatible with the current one. A version mismatch produces a warning badge on the card rather than a refusal, because in practice most changes remain compatible and blocking would be more disruptive than the risk warrants.

Four further checks arrive with v2.3, each catching something that would otherwise fail silently or expensively:

- **Declared facet keys are well-formed**, and any closed value set is consistent with the assets already in that namespace. A closed set narrowed while assets hold values outside it blocks the workflow until either the set is widened or those assets are superseded — one of the few places refusing to load is better than half-enforcing.
- **`[[limits]]` and `[[recovery]]` name step families that the workflow actually emits**, as far as this is knowable. A limit declared for a misspelled family silently leaves that step on the default, which is invisible until something hangs.
- **Declared capabilities are matched against what the provider adapters report** (§5.5). A workflow needing something unavailable is marked blocked with a message naming the capability, rather than failing after the script has been paid for.
- **Gates that can return more than approval declare `on_bypass`.** This cannot be checked statically from the manifest, so it is validated at the moment the gate event arrives; a gate missing it fails the run rather than being guessed at.

A manual **rescan** is exposed to the interface, because during development workflows are constantly edited while SFVF is running, and restarting the application every time would be tedious enough to discourage iteration.

### 5.2 Environment manager

Creates each workflow's isolated environment under `venvs/<id>/` and installs that workflow's dependency list plus the SDK.

It stores a hash of the dependency file. When the hash differs from the stored one, the dependencies are reinstalled before the next run. Using a hash rather than a timestamp means that touching the file without changing it does not trigger a needless reinstall.

If the workflow declares a Python version that is not present, the workflow is marked blocked with a message naming the version to install, rather than failing confusingly at launch.

### 5.3 Supervisor

Owns the lifecycle of a run: create the folders, freeze the instruction files, run the shared preparation phase, then start the video subprocesses up to the configured concurrency.

While they run it reads their output line by line, updates the records, pushes events to the browser, enforces the per-step time limits, and handles retries, cancellation and approval gates.

**Time limits measure silence, not elapsed time.** The limit for a step family is declared in `[[limits]]`, defaulting to the global figure, and the timer resets on every `heartbeat` event that step emits. Every SDK function that polls an external service heartbeats while waiting.

This distinction is the whole point of the mechanism. A video generation job may legitimately run for eleven minutes, and killing it means paying twice: once for the job that was abandoned and once for the retry, with the abandoned result possibly arriving afterwards and being discarded. Under an elapsed-time limit the only way to avoid that is to set limits so generous that a genuinely hung workflow runs until someone notices. Under a silence limit, a slow job is never killed and a hung one still is.

An **approval gate is never timed out**, because the elapsed time there measures how long the user took to answer rather than how long anything ran. Gates are recorded with their own duration so the record still shows where the time went, but that duration is excluded from step timing statistics, which would otherwise be distorted by however long the person was away from the machine. Time spent waiting on a provider is excluded for the same reason.

Under `video_semantics = "sequence"` the supervisor starts videos one at a time in index order regardless of the concurrency setting, passes each completed video's `Result.extra` into the next one's context, and cancels the remainder if one fails.

It holds in memory only what is currently in flight. Everything durable lives in files, so a backend restart loses live progress but no results.

### 5.4 Budget engine

Implements the reserve-then-reconcile scheme described in the PRD.

Before a priced call, the SDK asks the engine for a reservation. The engine immediately subtracts the estimated amount from the remaining budget and returns a token identifying that reservation. When the call finishes, the SDK reconciles the token with the real amount, and the difference is returned to or taken from the budget.

The reason for reserving rather than simply recording afterwards: with several steps running concurrently, each one that checks the budget before spending would see the full remaining amount, because none of the others have recorded anything yet. All of them would proceed, and together they would overshoot. Reserving makes each one's intention visible to the others immediately.

Meters are keyed by provider and never combined across credit providers, for the reason set out in the PRD. Exhaustion pauses the run and raises a prompt — except in a scheduled run, where there is nobody to answer, so it is skipped instead.

### 5.4a Forecasts

A workflow may declare, mid-run, what the remainder will cost:

```json
{"t":"forecast","meter":"higgsfield","unit":"credits","amount":720,"note":"60 shots"}
```

The engine records it as a soft reservation: visible on the card and in Statistics, but not itself blocking. It exists because the estimator described in the PRD matches against previous runs with the same `affects_cost` settings, which works for a workflow whose price follows from its settings and not at all for one whose price follows from how long the script turned out to be. The workflow is the only thing that knows, and it knows it before spending anything.

### 5.4b Atomic runs

For a workflow declaring `atomic = true`, an incomplete video has no value, so incremental spending is the wrong model.

**Pre-flight reserves the whole estimated run** and refuses to start if the available balance is below the estimate multiplied by the declared `safety_factor`. A forecast arriving mid-run triggers the same check immediately, which is what makes the difference between stopping at shot zero and stopping at shot forty.

**Exhaustion stops the run cleanly at a step boundary** rather than prompting and continuing. Everything already computed is kept, so resuming after a top-up re-runs pre-flight against only the remaining work. The status is `stopped-budget`, distinct from a user-requested `stopped` so that the interface can offer the obvious action.

**A scheduled atomic run** skips if pre-flight fails, and stops rather than skipping forward if the budget runs out mid-run — the work already done is recoverable, and skipping would strand it.

The reserve-then-reconcile scheme is unchanged underneath; atomic mode changes when the reservation happens and how large it is, not how it works.

Quota meters are read from the provider rather than accumulated locally. ElevenLabs reports characters used, the limit for the billing period and the reset time through its subscription endpoint, and that is the authoritative figure: characters spent from the same account outside SFVF would otherwise be invisible, and the pre-flight check would clear a run that cannot actually complete.

### 5.5 Provider layer

One adapter per provider. Each is responsible for its own authentication, its own rate limiting, and reporting its own costs in its own unit.

**A central rate limiter holds one queue per provider.** Every service caps how many requests it will accept in a period and rejects the excess. Without a deliberate queue, those rejections surface as apparently random step failures that are difficult to diagnose, because the same code works when run alone and fails when run alongside others.

This queue is also what bounds the two concurrency settings of §3.1a. Because both compose into it, neither needs to know about the other, and raising either cannot flood a provider.

**Each adapter declares its capabilities**, from a fixed vocabulary the chassis owns: `image.generate`, `image.edit`, `video.generate`, `video.refs`, `video.first_frame`, `agents.vision`, `agents.structured`. Workflows declare what they require, and the registry blocks a workflow whose requirements are unmet with a message naming the capability.

The vocabulary is deliberately coarse. A finer one — naming which reference *kinds* a given model accepts, say — would have to be maintained against providers whose surfaces move, and would be wrong more often than it was useful. Coarse declarations catch the case that matters, which is a workflow that cannot possibly work being started anyway; anything finer than that fails at the call, where the error is at least specific.

| Adapter | Authentication | Notes |
|---|---|---|
| OpenRouter | API key | Uses the OpenAI-compatible interface. Reports real per-call cost. Model identifiers must be pinned explicitly rather than relying on the provider's automatic fallback routing — otherwise the model that produced a given video is unknown, and the run is not reproducible. |
| ElevenLabs | API key | `GET /v1/voices` lists every voice the key can reach, cloned voices included, with a `category` field distinguishing premade, cloned, generated and professional, and paging driven by a `has_more` flag. `GET /v1/models` lists the speech models, each carrying a flag for whether it can do text to speech. `GET /v1/user/subscription` reports characters used, the period limit and the reset time. Speech is requested through the timestamped endpoint, which returns character-level alignment. Plan-level concurrency caps must be respected by the rate limiter. |
| Higgsfield | Official MCP server over OAuth | Hosted by Higgsfield and authenticated through the account, so no API key is stored. Work is submitted, then polled until finished, then downloaded. Credit cost varies by model and by resolution, so the estimate must account for both. Token refresh must survive a run lasting forty minutes or more. |
| Kinocut | Local, no authentication | The programmatic client is preferred over the MCP interface, because it is deterministic and therefore cacheable. |
| HyperFrames | Local, no authentication | Requires a headless Chromium browser and installed fonts. |

Isolating each provider in its own adapter is what makes the partly-unknown Higgsfield tool surface an acceptable risk: if the available tools differ from what was assumed, only that one file changes.

**Adapters also supply option lists.** Each adapter exposes a way to enumerate the choices it offers, so that the Run pop-up can be filled in from the account rather than from the manifest: voices and speech models from ElevenLabs, video models from Higgsfield, language models from OpenRouter. Three properties matter.

The results are cached with a short lifetime and refreshed when the pop-up opens, because these lists change on the provider's schedule and a stale dropdown that silently omits a voice added this morning is exactly the kind of failure that wastes an afternoon.

Every entry carries both a stable identifier and a display label, and it is the identifier that is written into `video.json`. Labels are marketing names and are renamed freely; an identifier recorded a year ago must still mean the same thing.

When a provider is unreachable, the adapter returns its last known list flagged as stale rather than raising. A run should not be blocked because a catalogue lookup failed, and the pre-flight check already covers the cases where the provider genuinely must be reachable. If a previously recorded identifier no longer appears in the list, it is still shown, marked as no longer offered, so that reopening an old request explains itself instead of silently selecting something else.

### 5.6 Secrets

Keys and tokens are held in an encrypted file. The passphrase is requested when the application starts and kept only in memory.

Storing the passphrase next to the encrypted file would make the encryption purely decorative, so it is not stored anywhere. The cost is one prompt per application start.

MCP connections authenticate through a one-time login in the browser, after which only the resulting token is saved. A token is preferable to a password on two counts: it can be revoked by the provider without changing anything else, and it grants access to that one service only, whereas a password is frequently reused and unlocks more than intended.

Secrets are passed into workflow subprocesses through the context file, and are removed from every record, log line and error message before anything is written to disk.

### 5.7 Scheduler

Reads `schedules.json`. When an entry is due it checks two conditions and acts accordingly: if that workflow already has an active run, the slot is skipped; if the budget is insufficient, the slot is skipped. Otherwise the Generation Request starts with the saved settings.

Missed slots are skipped rather than queued, because a queue would silently accumulate runs and then execute several at once, which is exactly the behaviour a person would not want from something that ran while they were asleep.

Each entry carries the flag determining whether approval gates pause or pass automatically.

### 5.8 Self-review

Runs as part of the mandatory finishing step, before a video is marked complete.

| Check | Method |
|---|---|
| The file is valid; duration and resolution are as expected | ffprobe |
| No black or visibly broken frames | sample frames at several positions and inspect them |
| Audio is neither silent nor clipping | measure audio levels |
| Captions are present when expected | compare against what the workflow declared |
| The video is not effectively a slideshow | measure how much the image actually changes over time |
| Nothing is drawn outside the frame or under the platform's interface | query the composition's DOM for bounding boxes crossing the viewport or the safe zone |
| No text is clipped mid-word | compare each element's scroll extent against its client box |
| Fonts actually loaded | check text nodes for fallback metrics |

The last three run only when a composition render was among the finishing inputs, and they exist because HTML written by an agent fails in ways no amount of frame sampling detects: a chart positioned off-screen, a heading truncated, captions under the platform's own buttons, or — the classic — a headless browser without fonts rendering every glyph as an empty box. In all of those the file is valid, the frames are not black, the audio is fine, and the video is unusable.

**Thresholds follow the declared `[output]` format.** The slideshow measurement in particular cannot be one number: a slow establishing shot in a six-minute episode is normal, and the same measurement in a forty-five-second vertical short means something has gone wrong.

None of this involves AI. All of it is cheap. The reason it earns its place is that these are precisely the failures a person only discovers by watching the whole video, which is the most expensive way to find them.

Failure marks the video failed rather than presenting it. All results are written into `video.json`, so a borderline case can be inspected afterwards.

### 5.9 Cache

Results are stored content-addressed, under a key derived from hashing the workflow's version, the step's **family**, and its declared inputs in canonical form. Canonical form matters: without a fixed ordering, the same inputs written in a different order would hash differently and every lookup would miss.

**Any filesystem path appearing in a step's inputs is hashed by the file's contents rather than by the path string.** Without this, a step keyed on an uploaded reference video would miss on every run, because the path contains the run identifier — and worse, a *different* file arriving at the same path would hit. Since the workflows that take media as input are exactly the ones whose steps are most expensive, getting this wrong would be costly in both directions at once.

A step's `label` is not part of the key. Rewording a display string must never invalidate paid work.

Two partitions with different deletion policies:

- **`cache/paid/`** holds results of paid generation. Never deleted automatically. These were expensive and slow to produce, and losing one costs real money to replace.
- **`cache/cheap/`** holds renders and research results. Deleted least-recently-used first once the total exceeds a configured size. These are cheap and fast to reproduce, so keeping them indefinitely buys little.

Step results that are files rather than data are stored by content hash and copied back into the video's folder when a cached result is used.

### 5.10 Library

Holds assets that outlive any run: reference art, location plates, style references, and small persistent state such as where a series left off. §2.1b explains why this is a separate store from the cache rather than a partition of it.

**Layout and authority.** One namespace per body of work, defaulting to the workflow id and shared by declaration. Each asset is a blob named by its content hash with a descriptor sidecar beside it. The sidecars are authoritative; `catalog.json` is an index that exists so that a facet query does not have to open several hundred files, and it is rebuilt by rescanning `items/` whenever it is doubted.

**Write order: blob, then sidecar, then catalogue entry.** This ordering makes every crash recoverable by inspection alone:

| Found on rescan | Meaning | Action |
|---|---|---|
| Blob with no sidecar | crashed before describing | quarantine and flag — never delete, it cost money |
| Sidecar with no blob | corruption; impossible under this ordering | drop from the catalogue, flag |
| Both present, not indexed | crashed before indexing | index it |

Writes are atomic — write to a temporary name, then rename — so a torn file is not among the possibilities.

**Retrieval is two-tiered and the split is a cost mechanism.** Facet filtering is exact-match, deterministic and free; it narrows three hundred assets to five. Only then does an agent read the descriptions and choose. Showing every candidate to a vision model on every selection would make reuse more expensive than regeneration, which would defeat the point of having a library.

**Facet vocabulary is declared, normalised, and never guessed at.** Undeclared keys are rejected at write. Open values are lowercased, trimmed and hyphenated so trivial variants converge mechanically. Beyond that the chassis announces rather than corrects: a first-seen value emits a `library` event and is marked novel in the catalogue. Automatic merging by similarity is deliberately absent — a system that quietly decides two facet values mean the same thing will eventually be wrong invisibly, which costs more than the duplicate asset it would have prevented.

**Nothing is overwritten and nothing is auto-evicted.** A redesigned asset is a new one whose descriptor names what it supersedes; the old one's status changes so that `find(status="active")` skips it while past records still resolve. Deletion is a manual action in the interface, writes a tombstone, and physically removes the blob only when no `video.json` references its id — a bounded scan, performed rarely. The alternative is a dangling reference or a falsified record, and both are worse than a file left on disk.

**In dry run**, reads hit the real library and writes go to an overlay under the video folder which is discarded at the end. This is what allows a free rehearsal of the branch that actually matters — most assets found, one missing, generate that one — without leaving stubs behind.

**Concurrency.** Only one run per workflow, but two workflows may share a namespace, so the only contended object is `catalog.json`. Because it is derived and its rebuild is idempotent, a torn catalogue self-heals on the next rescan. No locking in v1; if this ever bites, the fix is a lock around rebuild, not a database.

### 5.11 Learning

For a chosen workflow: gather every `video.json` containing quality answers since the last learning run, load that workflow's criteria files together with its current rules and skills, and run the SkillOpt-derived optimiser to propose bounded edits.

Three constraints are enforced by the module itself rather than left to convention:

**Only files inside `workflows/<id>/rules/` and `workflows/<id>/skills/` may be modified.** Any proposal touching a path outside that is rejected outright. Global instructions are unreachable by this process, because a change there would silently affect every workflow including ones the user was not reviewing.

**The library is unreachable too, and for a stronger version of the same reason.** Descriptors, caveats and facets may be *read* as evidence — "coherence drifts at shot 4" is far more actionable when the record shows which reference sheet shot 4 used — but never written. An optimiser editing a caveat would change what the selection agent chooses, which changes which references reach generation, which changes what every future episode looks like, through a causal chain nobody will reconstruct from a diff of a metadata file. The correct lever is the selection agent's rules, which are inside the permitted set.

**Proposals are written to a staging area and never applied directly.** The live files are untouched until the user accepts.

**Acceptance archives the previous version.** The prior file moves to `archive/` and the version number in its frontmatter increments, so that the record of which instructions produced which past video stays accurate.

On any error, the staging area is discarded and the learning run returns entirely to its state before it began, with nothing modified.

---

## 6. Frontend structure

| Route | Content |
|---|---|
| `/` | Main tab — the workflow grid |
| `/workflow/:id` | The video list, grouped by Generation Request |
| `/workflow/:id/video/:run/:idx` | One video's full record, including replay |
| `/schedule` | Scheduled entries |
| `/learning` | The Learning tab and the review interface |
| `/statistics` | Spend over time, separated by meter |
| `/library/:namespace` | Assets with their descriptors; edit caveats, repoint aliases (see below) |
| `/settings` | Keys, connections, defaults |

The two video views are pseudo-tabs: they are not listed in the tab bar, they are closed by the red button in the top-right corner, and closing one restores the previous tab at the scroll position it was left at.

**The Library view is deferred past version 1.** Until it exists, descriptors are written by workflows and inspected as files, which is workable because they are plain JSON. It is listed here so the route is reserved and the eventual view is not treated as a redesign.

**Gates render according to their declared shape.** A plain approval gate is a dialog with a payload; a selection gate is a grid of items with their artifacts, each independently kept or marked for redo, plus a free-text note. The artifacts are fetched from the video folder through the same file-serving route that the detail view uses, so no new transport is involved. The note matters more than it looks: it is the input to the regeneration prompt, and it is recorded in `video.json`.

Live state arrives over a single Server-Sent Events connection carrying supervisor events. The frontend holds no authoritative state of its own — everything it displays came from the backend, so there is never a question of which copy is correct.

---

## 7. Build order

Each stage should be genuinely usable before the next begins, so that problems surface while there is still little built on top of them.

1. **Skeleton.** Backend, registry, manifest validation, and the workflow grid rendering from files on disk. Nothing runs yet, but the shape is visible.
2. **Execution.** Environment management, subprocess launching, reading the event stream, creating run folders, live progress in the interface. Heartbeat-based step limits belong here rather than later: retrofitting the timer once workflows depend on kill-and-retry behaviour means re-testing every long-running path.
3. **The SDK.** The context object, the step mechanism *in its final family/inputs/label form*, checkpointing and caching including content-hashing of paths, `ctx.map()`, and dry-run stubs. The step signature is cheap to settle now and touches everything downstream, which is why it is not deferred.
4. **The example workflow.** Composition-based, deterministic, nearly free. Iterating on it is how the plug-in interface gets validated while changing it is still cheap.
5. **Providers**, in ascending order of cost to debug: OpenRouter, then ElevenLabs, then HyperFrames and Kinocut, then Higgsfield last. **The provider spikes of §9 run before the Higgsfield adapter is written**, because their outcomes determine what its interface needs to be.
6. **Money.** Budget engine, meters, estimation, forecasts, atomic pre-flight, the Statistics tab.
7. **The library.** Descriptors, catalogue, retrieval, dry-run overlay. Placed here deliberately: nothing before it needs it, and designing a descriptor schema before a single real asset exists means designing against imagined content.
8. **Records and review.** The video detail view, replay, self-review including the composition checks.
9. **Gates, scheduling, and quality capture.** The selection gate shape arrives with the rest of the gate work.
10. **Learning.**

Learning is deliberately last, and not only because it is complex. It depends on accumulated quality judgements, which cannot exist until everything else has been producing videos for long enough to judge.

---

## 8. Standing rules for the coding agents building this

**The plug-in interface is not vibe coded.** The manifest schema, the event protocol and the context object are specified in the Workflow Authoring Guide. Implement them as written. Everything inside a workflow is free-form; everything at the boundary is not.

**Keep no authoritative state in backend memory.** Run state lives in files. The supervisor holds only what is currently in flight. This is what allows the backend to be restarted without losing anything that was already finished.

**Never write into `workflows/`, `rules/` or `skills/` while running.** The learning module is the single exception, and even it writes to a staging area rather than to the live files. `library/` is *not* covered by this rule — it is written to while running, by design, which is precisely why it is not inside `workflows/`.

**Every priced call goes through the budget engine.** A code path that spends money without reserving first is a bug even when it appears to work, because the failure it causes only appears under concurrency and is very hard to trace afterwards.

**Never make the library invalidate the cache wholesale.** Library membership is not a step input. Steps declare specific asset ids, and only those ids affect their keys. An implementation that folds "the state of the library" into a cache key will invalidate every stored result the first time an unrelated asset is added.

**Preserve the descriptor/blob keying asymmetry.** Selection steps key on descriptor hashes so that new candidates and new caveats are reconsidered; generation steps key on blob ids so that annotating an asset never invalidates work that used it. Collapsing these into one is an easy simplification to make and turns every metadata edit into a regeneration bill.

**Redact secrets on every path that writes.** Records, logs, the event stream, and error messages all need it — error messages especially, because they are the place secrets most often escape by accident.

**Be strict at the boundary and tolerant inside it.** Manifest and settings validation should reject bad input clearly and early, with a message naming the specific problem. The event parser should absorb malformed output rather than crash, because a workflow printing something unexpected is normal and should not end a run.

---

## 9. Open questions that must be answered by experiment

Three assumptions in this document cannot be settled by reasoning, and two of them are load-bearing for planned workflows. Each is cheap to test and should be tested before the code that depends on it is written.

### 9.1 Reference-conditioned generation on Higgsfield

**Question.** Does the MCP server accept reference images or a reference video as conditioning, in what form, and with what fidelity to a supplied character design?

**Method.** Connect the server, enumerate the tool surface, attempt one generation with a character image attached, then one with a source clip as a motion reference. Half a day, a few euros of credits.

**Why first.** Both planned heavy workflows depend on it, and §5.5 already records that the tool surface is unconfirmed and expected to move. This is the assumption most capable of invalidating a large part of the design.

**Consequences.** If supported, the `refs` argument is implemented as specified. If only first-frame conditioning is available, character consistency shifts to generating a still from the reference sheet and conditioning the clip on it — workable, more steps, more cost per shot. If unsupported entirely, the consistency strategy for character-driven workflows must be reconsidered, and it is far better to discover that before the library holds the assets it would have used.

### 9.2 Multi-view reference generation

**Question.** Can a reachable image model produce a usable character turnaround whose views actually depict one consistent character?

**Method.** Three subjects, three prompt strategies, judged on cross-view consistency. A day, a few euros.

**Consequences.** If not, the library's *contents* change while its mechanism does not: instead of one sheet per character, a set of independently generated single-view references plus tighter prompt discipline, with drift caught by the intake vision pass rather than prevented by the sheet.

### 9.3 Kinocut at episode length

**Question.** Is the programmatic interface comfortable with sixty clips and multi-track dialogue mixed against music, or is it shaped for short agent-driven edits?

**Method.** Assemble sixty stub clips with three audio tracks; inspect the output and the time taken. Half a day, free.

**Consequences.** If uncomfortable, assembly happens in stages — scene-level edits cached as steps, then a final concatenation — which is better practice anyway and costs structure in the workflow rather than a chassis change. If it fails outright, direct FFmpeg for assembly with Kinocut retained for what it does well, at the cost of the single-toolchain argument in the PRD.
