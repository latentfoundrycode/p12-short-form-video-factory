# Short-Form Video Factory (SFVF) — Product Requirement Document

**Version:** 2.3
**Status:** Pre-implementation
**Audience:** The developer and the coding agents building this application.

---

## 0. How to read this document

This document describes *what* SFVF should be and *why* it should be that way. A companion document, the Architecture Blueprint, describes *how* to build it. A third document, the Workflow Authoring Guide, describes how to write the plug-ins that run inside it.

Wherever a decision could reasonably have gone the other way, the reasoning is written out rather than assumed. This is deliberate. A design decision whose justification exists only in someone's memory will be reversed by accident within a month.

---

## 1. Glossary

These terms recur throughout all three documents. They are defined once, here.

**Workflow (also: plug-in).** A self-contained production pipeline that makes one specific kind of video. It lives in its own folder and consists of a manifest file plus program code. "Plug-in" and "workflow" mean the same thing in this project; workflow is used in the interface, plug-in when discussing architecture.

**Manifest.** A small configuration file (`workflow.toml`) in which a workflow declares facts about itself: its name, version, what settings it accepts, which services it needs access to. SFVF reads this before running anything, so it knows what to display and what to check. A manifest is a *declaration*; it contains no logic.

**Generation Request.** One press of the "Initiate" button. A Generation Request produces some number of videos, all of them on the same topic. It has its own folder, its own budget, and its own record of what happened.

**Step.** A unit of work inside a workflow — for example "write the script" or "generate shot 3". Steps matter because SFVF remembers the result of each one, which is what makes it possible to stop a run and continue it later without repeating work you already paid for. A step is named by its *family*, which says what kind of work it is: an episode with sixty shots has sixty steps of one family.

**Checkpoint.** The saved result of a completed step. When a run resumes, completed steps return their checkpointed result immediately instead of executing again.

**Cache.** A store of previous step results shared across runs, so that identical work is never paid for twice — even across different Generation Requests.

**Library.** A durable store of reusable assets belonging to a body of work rather than to any one run: character reference sheets, location plates, style references, and small persistent state such as where a series left off. The cache remembers *work*; the library holds *things*. Unlike the cache, it is named and described rather than keyed by an opaque hash, it survives changes to a workflow's version, and nothing in it is ever deleted automatically.

**Asset.** One item in the library, identified by the hash of its contents and accompanied by a written description of what it actually is.

**Rule.** A short markdown file containing instructions given to an AI agent every time it is called. Rules are always loaded.

**Skill.** A longer markdown file containing reference material an agent reads only when it needs it. Skills are loaded on demand, by name.

**Frontmatter.** A small block at the very top of a markdown file, fenced by three dashes, containing structured settings rather than prose. SFVF uses it to record which agents a rule applies to and what version it is.

**Agent.** An AI model performing a specific job inside a workflow — researching, writing the script, describing a shot, judging quality. Different agents receive different rules.

**Quality factor.** A question, defined by each workflow, that the user answers in words about each finished video.

**Learning run.** A user-initiated process that reads accumulated quality answers and proposes improvements to a workflow's rule and skill files. Proposals are always reviewed before they take effect.

**Provider-supplied option list.** A set of choices for a setting that is read from a provider when the Run pop-up opens, rather than written into the manifest. Voices and video models both work this way, because both are account-specific and both change without notice.

**Meter.** A thing that gets consumed when the application does work — money, provider credits, or a monthly character allowance. Different providers use different meters, and they cannot be added together.

**MCP (Model Context Protocol).** An open standard, published by Anthropic, that lets an application expose its capabilities to AI systems as callable tools. Higgsfield and Kinocut both provide MCP interfaces.

**OAuth.** A standard login method in which you sign in through the provider's own web page, and the provider hands back a token — a long random string that grants access. The application stores the token rather than your password. Tokens can be revoked by the provider and are limited to that one service, which is why they are safer to store than a password.

**Headless browser.** A web browser running invisibly, with no window on screen. HyperFrames uses one to draw each video frame as if it were a web page, then encodes those frames into a video file.

**Isolated environment (Python virtual environment).** A private folder containing a workflow's own copies of the software libraries it depends on. Because each workflow has its own, two workflows can require incompatible versions of the same library without ever interfering with one another.

**Dry run.** A mode in which the workflow executes normally but every paid service call is replaced with a fake, free result. Used to test the shape of a pipeline without spending anything.

**Gate.** A point in a workflow where execution pauses and waits for the user before continuing. A gate may ask for plain approval, for a choice between named options, or for a selection over a set of items — keeping most of them and sending some back to be redone.

**Safe zone.** The area of the screen where the publishing platform overlays its own interface (buttons, captions, username). Anything important placed there gets covered up.

---

## 2. Purpose

SFVF is a single-user application that generates video by running **workflows** — pluggable production pipelines that each produce one specific kind of video.

Its centre of gravity is short-form vertical video of the kind published to TikTok and similar platforms, and that remains the default format. But the plug-in boundary was drawn to accommodate whatever a workflow turns out to be, and some will not fit that description: a serial animated episode in 16:9, running for minutes rather than seconds, posted somewhere that draws no interface over the frame. **The format is a workflow's declaration, not a property of SFVF.** Anywhere this document says something about the shape of a video, it is describing the default rather than a constraint, and §4 says which parts are which.

SFVF itself produces no videos at all. It provides the surrounding machinery: finding workflows, configuring them, running them, paying for them, remembering what happened, remembering the assets they reuse, running them on a schedule, and improving them over time from the user's own judgements.

One distinction governs nearly every decision in this document:

- **A workflow encodes creative decisions.** What kind of video this is, what the script sounds like, which shots get generated, how they are cut together, what makes one output better than another.
- **SFVF encodes everything else.** Running things, paying for things, remembering things, and not losing things.

The reason this line is drawn where it is: workflows will be written quickly and loosely, largely by AI coding assistants, and will be rewritten often. Anything placed inside a workflow is therefore cheap to change and cheap to get wrong. Anything placed in the chassis is expensive to change once several workflows depend on it, but is written once and gets steadily more reliable. So the rule is that anything two workflows would both need, and neither would want to do differently, belongs in the chassis.

This is also why the interface between the two is specified by hand while the workflows themselves are not. Code inside a workflow can be thrown away. An interface that five workflows already depend on cannot.

---

## 3. Scope

### 3.1 What "version 1" means

Defining this matters more than it might appear. A project of this kind expands indefinitely unless someone writes down what "finished" means, because every feature suggests two more. The following list is the boundary. Anything beyond it is a later version, not a missing piece.

SFVF is version-1 complete when all of the following are true:

1. Workflows are found automatically on disk and displayed as a grid of cards.
2. A Generation Request can be configured and started from the interface, producing a chosen number of videos.
3. Runs have a budget, can be stopped and resumed without losing paid work, and can be cancelled cleanly.
4. Every video is saved together with a complete record of how it was made.
5. Videos can be watched and deleted inside the application.
6. Scheduled runs execute without anyone present.
7. Quality factors can be answered and the videos of a request ranked, and a learning run can propose changes to a workflow's instructions for review.
8. Workflows can keep and reuse assets between runs, with enough recorded about each one to choose between them without looking.
9. One example workflow ships and produces a publishable video from beginning to end.

### 3.2 What is deliberately excluded

These are not oversights. They are choices, listed so that nobody — human or coding agent — quietly builds them.

- **Publishing or uploading.** SFVF produces files. Uploading them to any platform is done manually by the user. This keeps the application out of every platform's API terms, review processes and rate limits.
- **Multiple users, accounts, permissions.** There is exactly one user. Everything that would exist to separate users is unnecessary complexity.
- **A mobile or tablet interface.**
- **Cloud or distributed rendering.** Everything runs on one machine.
- **Automated backup.** SFVF will not manage backups. The things worth copying elsewhere are `runs/`, `library/`, `workflows/`, `rules/`, `skills/` and the encrypted secrets file.
- **Local text-to-speech.** Deferred beyond version 1. The reasoning appears in §6.4.
- **Automated virality or quality scoring services.** The reasoning appears in §11.2.
- **A browsing interface for reusable assets.** The library itself is version-1; a screen for inspecting it, editing an asset's notes by hand and repointing names is not. Until then those files are plain text and can be read directly, which is enough to work with and not enough to be pleasant.
- **A first-class notion of a series.** A workflow may produce episodes, carry state between them and be run one episode at a time, all of which version 1 supports. What it does not get is a screen that presents a series as a single object with its own record. That can be added later without changing anything beneath it.
- **Creating voices, or any other durable state inside a provider's account.** The reasoning appears in §6.6.

---

## 4. Video specification

**The default is vertical, 9:16, at 1080 × 1920 pixels.** A workflow that makes something else declares it — aspect ratio, frame rate, and whether platform safe zones apply at all. The declaration exists because a six-minute 16:9 episode and a forty-five-second vertical short are not the same object, and forcing both through one specification would mean one of them is always being treated as a defective version of the other.

**Safe zones are enforced by the chassis** rather than left to each workflow to remember. The publishing platform draws its own interface over parts of the video: buttons down the right-hand side, the caption and username along the bottom, and occasionally elements at the top. Anything placed there is partially or wholly hidden. The reserved regions are the bottom 15%, the right 15%, and the top 10% of the frame. These are provided to compositions as a stylesheet they import, so that a workflow gets the correct margins by using the chassis rather than by remembering a number. A workflow declaring no safe zone receives no margins, rather than margins for a platform it will never be posted to.

A single mandatory finishing step applies a consistent codec, frame rate, and loudness normalisation to every video of a given declared format, regardless of which workflow produced it. Without this, output would vary in volume and encoding depending on which pipeline made it, and the differences would only become apparent after upload.

**The automatic quality checks are calibrated per format** for the same reason. The check for "this is effectively a slideshow" cannot be one threshold: a slow establishing shot is normal in a long episode and a symptom of failure in a short.

The cover frame — the still image used as the video's thumbnail — defaults to the frame at one second in. Workflows may override this.

---

## 5. Concepts in the interface

| Concept | What it is |
|---|---|
| **Workflow** | A plug-in producing one kind of video |
| **Generation Request** | One press of Initiate, producing N videos on one topic |
| **Video** | One output, with its own folder, intermediate files and record |
| **Step** | A remembered, repeatable unit of work inside a workflow |
| **Library** | Reusable assets a workflow keeps between runs, with descriptions |
| **Gate** | A pause where the user approves, rejects, or selects before work continues |
| **Rule / Skill** | Instructions given to AI agents; always-loaded and on-demand respectively |
| **Quality factor** | A question the user answers about each finished video |
| **Learning run** | A user-initiated process that proposes improvements to a workflow's instructions |

### 5.1 What "N videos" means, and when it means something else

By default a Generation Request produces N **variants**: several attempts at the same brief, independent of one another, produced in parallel and ranked against each other afterwards. This is what makes the statistical approach to failure work — make five, keep the good ones, discard the rest.

A workflow may instead declare that its videos are a **sequence**: episodes rather than alternatives. Then they run one at a time in order, each can read where the previous one ended, and a failure stops the rest rather than letting them proceed on a foundation that does not exist.

This distinction earns a place in the requirements because it changes the economics of everything else. Producing five variants and discarding four is sensible at thirty cents a video and indefensible at twenty-five euros. So a workflow may also declare a **maximum** number of videos, and may declare itself **atomic** — meaning a half-finished video is worth nothing, so the budget is committed up front and running out stops the run cleanly for later resumption rather than leaving a folder of unusable paid fragments.

---

## 6. The technology stack

### 6.1 Chosen components

| Role | Choice | What it does here |
|---|---|---|
| AI agents / language models | **OpenRouter** | A single gateway providing access to many different language models through one account and one key. Also reports the real cost of every call, which is what makes accurate budget tracking possible. |
| Video generation | **Higgsfield**, via its official MCP server | Generates video clips from prompts. Clips are limited to roughly fifteen seconds. The server is hosted by Higgsfield, authenticated with OAuth through the account rather than an API key, and fronts thirty or more models whose credit cost varies by model and resolution. |
| Still image generation | **A provider adapter**, initially Higgsfield's image models | Character reference sheets, location plates, style references, and the first frames that longer sequences are chained from. Which provider backs this is deliberately left to the adapter layer; see §6.5. |
| Speech | **ElevenLabs** | Converts the script into narration and returns alignment data for it. The API returns *character*-level start and end times; the chassis groups these into word timings, which is what caption synchronisation needs. |
| Motion graphics and composition | **HyperFrames** | Renders a video from an HTML page. Used for animated text, titles, charts, and any designed visual element. |
| Cutting, audio mixing, assembly | **Kinocut** | A local video-editing engine built on FFmpeg, designed for AI agents, with a programmatic interface. |
| Shot boundary detection | **PySceneDetect** | Finds the points in an existing video where one shot ends and the next begins. |
| Music | **Epidemic Sound** | Licensed music, so that uploads do not attract copyright claims. |
| Learning | **SkillOpt** (open-source) | Proposes improvements to instruction documents based on scored outcomes. |

### 6.2 Why HyperFrames rather than Remotion

Both HyperFrames and Remotion do the same job: they turn code into video. You write code describing what should appear on screen at each moment; a headless browser draws every frame; the frames are encoded into a video file. Both use the same underlying components — headless Chrome and FFmpeg — so the raw quality of the output is effectively identical. This is not a case where one tool can do something the other cannot.

The difference is what you write. Remotion expects React components, which is a specific JavaScript framework with its own conventions. HyperFrames expects a plain HTML file.

Three arguments decide this in favour of HyperFrames for this project specifically:

**First, and most importantly, the workflows here are written by AI coding assistants.** Language models have been trained on an enormous quantity of plain HTML and comparatively little Remotion-flavoured React, so they produce correct HTML motion graphics far more reliably. Since the whole premise of this project is that workflows are written quickly by an assistant, the format the assistant writes best is the format that should be used.

**Second, animation libraries conflict with React's model.** Libraries such as GSAP maintain their own internal clock to drive animations. React redraws the screen on its own schedule, and reconciling those two timing systems is a known source of friction. HyperFrames sidesteps this because there is no framework in between.

**Third, licensing.** HyperFrames is Apache-2.0 with no restrictions on team size. Remotion is free for individuals and companies up to three people, but requires a paid licence above that, starting at a hundred dollars a month. For a single user today Remotion would also be free, so this is not decisive — but it removes a future question entirely.

Remotion's genuine advantages are its maturity, its far larger community, its distributed rendering service that spreads a render across many machines, and its visual editing environment with a timeline and scrubber. None of these matter for a single-user application rendering short videos on one computer. **Remotion is therefore not used at all.** Using both would mean maintaining two composition systems, two sets of instruction files, and two sets of styling conventions, for one capability.

### 6.3 Why Kinocut rather than CapCut

These two are not equivalent, and the choice is about risk rather than capability.

The CapCut MCP integrations available are all unofficial. They are community projects that manipulate CapCut's internal project files, and they require a separate third-party backend server to be running. CapCut's file format is undocumented and belongs to ByteDance, who have no reason to keep it stable. Putting that on the critical path of a pipeline that runs unattended on a schedule means accepting that a silent update could break automated runs at any time.

Kinocut is a video-editing engine built on FFmpeg specifically for AI agents. It runs entirely on the local machine, is Apache-2.0 licensed, and includes validation that prevents an agent from silently producing broken output. It already integrates HyperFrames, so the composition engine and the cutting engine belong to the same toolchain rather than being two unrelated systems glued together.

The decisive feature is that **Kinocut provides an ordinary programmatic interface alongside its MCP interface.** This matters because of how SFVF handles repeatability. When an AI agent decides which tools to call and in what order, the same input produces different results each time, which destroys the ability to remember and reuse work. By calling Kinocut as ordinary code, an edit becomes deterministic — the same inputs always produce the same output — and can therefore be checkpointed and cached like any other step. The MCP interface remains available for a workflow that genuinely wants an agent making editing decisions, with the understanding that such steps cannot be cached.

**CapCut is therefore not used.**

### 6.4 Deliberately rejected, with reasons

**Remotion** — redundant with HyperFrames; see §6.2.

**CapCut MCP** — fragility; see §6.3.

**Hugging Face Inference** — OpenRouter already provides access to substantially the same open models. Adding a second gateway would mean two API keys, two different cost-reporting formats, and two independent sets of failure modes, in exchange for no capability that is not already available.

**LangChain and LangGraph** — These are frameworks for orchestrating AI agents. They are not used, for four reasons. First, SFVF is not an agent orchestrator; it is a process supervisor that remembers what has been done. Its own step mechanism already provides checkpointing, caching, resumption and cancellation, and LangGraph would introduce a second, competing memory system in a different location, forcing an arbitrary choice about which one is authoritative. Second, the pipelines are mostly linear — research, then script, then prompts, then generation, then speech, then editing — which is a sequence of function calls rather than a state machine. Third, these frameworks change their interfaces frequently, and an AI assistant generating code for them tends to mix several incompatible generations of that interface together. Fourth, accurate cost recording and pinned model identifiers are trivial through a thin wrapper of our own and awkward through a framework's callback system. If a specific workflow later needs a genuine agent loop, it can install whatever framework it likes inside its own isolated environment without affecting anything else.

**Automated virality prediction** — The available tools are beta-stage, their "brain activation" framing is marketing rather than validated science, and virality is genuinely difficult to forecast. More importantly, the user's own judgement is a better signal and is already being captured. See §11.

**Local text-to-speech, for now** — ElevenLabs provides both high quality and word-level timing information, and the timings are what caption synchronisation depends on. A local model would require downloading model weights, probably a GPU, and an additional alignment step to recover timings that ElevenLabs supplies directly. That is a large dependency added for a capability already covered. The speech interface in the chassis is designed so a local option can be added later without any workflow changing.

### 6.5 Why the image provider is not named

Every other row in §6.1 names a specific service. The image row names a capability instead, deliberately.

Still-image generation is the least settled part of this stack. Whether any reachable model can produce a genuinely consistent multi-view character reference is an open question that must be answered by experiment rather than by reading documentation, and the answer may well be that today's best option is replaced within the year. Committing the requirements to a provider whose suitability is unverified would mean either revising this document when the experiment fails, or — worse — building around a decision nobody re-examined.

What matters at the requirements level is that the capability exists behind an adapter, that workflows declare they need it, and that a workflow requiring it cannot be started when it is unavailable. Which service fills it is an implementation decision recorded in the Architecture Blueprint.

### 6.6 Why SFVF does not create voices

A workflow with eight recurring characters needs eight distinct voices, and it would be natural to expect SFVF to make them.

It does not. Voices are created by hand in the provider's own interface, and a workflow keeps the resulting identifiers in its own configuration file.

The reason is that voice creation makes durable state *outside* SFVF that nothing inside it represents. Every other paid call produces a result that is stored, recorded and attributable; a created voice produces an account-level object that outlives the run, cannot be discovered by any later scan, and cannot be attributed to the video that caused it. Lose the record and there is an orphan in the account that SFVF has no way to see or clean up. It also has no sensible caching behaviour, since the same inputs do not produce the same voice.

The cost of this refusal is some manual copying when a cast is first assembled. The cost of the alternative is a category of spending the application cannot account for, which is precisely what §7 exists to prevent.

---

## 7. Money

Cost control is a first-class feature rather than a safeguard bolted on afterwards, because the failure mode being prevented is real: a pipeline that loops on a quality check, or a run misconfigured to produce twenty videos instead of two, can spend a substantial amount before anyone notices.

### 7.1 Three kinds of meter

Not everything that gets consumed is money, and the different kinds cannot be added together.

| Meter type | Provider | Unit | What happens when it runs out |
|---|---|---|---|
| **Fiat currency** | OpenRouter | Euros | The run pauses and asks whether to raise the budget |
| **Credits** | Higgsfield | Provider-specific credits | The run pauses and asks whether to raise the budget |
| **Quota** | ElevenLabs | Characters per month | Displayed and tracked; cannot be topped up mid-month. The characters used, the monthly limit and the reset date are read from the provider rather than counted locally, so the figure stays correct even when characters are spent outside SFVF |

The distinction between credits and quota matters. Credits are purchased and can be bought again. A monthly character quota simply runs out until the billing period resets, so "raise the budget" is not a meaningful response — the only useful behaviour is to show clearly how much of the month a given Generation Request consumed.

**Providers billed in real currency share a single budget line**, because euros are euros regardless of who receives them.

**Credit-based providers never share a line with one another.** This is not a cosmetic decision: one provider's credit is not comparable to another's, since each sets its own scaling and its own prices per model and resolution. Summing them would produce a number that means nothing. Each credit provider therefore gets its own labelled meter, named after the provider.

Epidemic Sound is a flat subscription with no per-use metering, so it is not tracked at all. Kinocut, HyperFrames and PySceneDetect run locally and cost nothing, so they never appear.

Learning runs consume OpenRouter currency, because the optimiser makes language-model calls. They are budgeted separately from Generation Requests so that improving a workflow never eats the budget set aside for producing videos.

### 7.2 How a budget is spent

Each Generation Request carries its own budget, set before it starts, with one line for each active meter.

**Before the run can start**, SFVF checks that the relevant provider balances are actually sufficient — enough Higgsfield credits, enough remaining ElevenLabs characters. Discovering that credits ran out seven shots into a nine-shot video wastes both time and the money already spent on the first six.

**When the settings pop-up is open**, an estimate is shown for each meter, calculated as described in §7.3.

**Before each priced call**, the estimated cost is subtracted from the remaining budget immediately, before the call is made. This is the part that is easy to omit and important to include. If several steps are running at the same time and each only records its cost after finishing, every one of them will look at the budget, see plenty remaining, and proceed — and collectively they will overshoot. Deducting the estimate up front prevents that.

**When the call completes**, the provisional deduction is replaced with the actual figure, which the provider reports.

**When a budget is exhausted**, the run pauses and asks whether to raise it or stop. A scheduled run behaves differently: with nobody present to answer, it is silently skipped rather than left waiting.

### 7.3 Estimating cost before a run

Cost is recorded **per video** rather than per Generation Request. This is deliberate: if history were stored per request, then requests for one video, three videos and five videos would each need their own separate history, and none would ever accumulate enough examples to be useful. Storing cost per video makes the video count a simple multiplier instead.

Estimates are drawn from the last ten comparable runs. "Comparable" means matching on the parameters that actually influence cost, which each workflow declares in its manifest — the choice of model, the target duration, the number of shots. Free-text parameters such as the topic are excluded, because they are different every single time, so including them would guarantee that no two runs ever match and the estimate would always fall back to a crude average.

Three categories of run are excluded from the history. Failed and stopped runs are excluded because they only paid for part of the work and would drag the average downwards. Dry runs are excluded because they cost nothing. Beyond that, each run records both what it actually cost and what it *would have* cost without reusing any remembered results — and it is the second figure that feeds estimates, because a resumed run that reused six cached steps tells you nothing about the price of a fresh one.

The estimate always states its own confidence in plain terms: matched against similar runs, with the number of matches; or a workflow-wide average, explicitly marked as crude; or no data at all.

### 7.4 When the workflow knows better than the estimator

The scheme in §7.3 works for a workflow whose price follows from its settings. It does not work at all for one whose price follows from something not yet known when the settings were fixed — an episode whose shot count depends on how the script turned out, or a reference video whose length nobody measured before uploading it.

So a workflow may **forecast**: state, once it knows, what the remainder of the run will cost. The forecast is shown on the card and in the Statistics tab beside the historical estimate, and it is recorded next to actual spend so that how wrong it was is measurable rather than merely felt.

A forecast does not by itself stop anything. Its value is timing: it arrives after the script and before the first paid clip, which is the one moment where knowing the number can still prevent the expense rather than merely explain it.

### 7.5 Workflows where partial output is worthless

The behaviour in §7.2 — pause, ask, continue — assumes that what has already been produced retains its value. For a set of variants it does: four finished videos out of five is a good afternoon.

For a serial episode it does not. Forty shots of sixty is not two-thirds of an episode; it is nothing, plus a bill.

A workflow may therefore declare itself **atomic**, which changes three things. The whole run is committed against the budget before it starts, with a margin the workflow declares, so an underfunded run is refused rather than begun. Exhaustion mid-run **stops the run cleanly** rather than pausing for a decision, keeping every completed step so that a top-up and a resume pay only for what is left. And such a request never reports the outcome as partial success, because it was not one.

---

## 8. The interface

Four tabs — **Main**, **Schedule**, **Learning**, **Statistics** — plus **Settings**.

### 8.1 Main tab

A grid of workflow cards. Each card shows the workflow's title, its thumbnail if one has been supplied, a brief description, the average cost per meter across the last ten runs, whether it is currently running, and if so which stage it has reached, expressed as the workflow itself reports it — for example "3/7 — Generating shots". A **Run Workflow** button sits at the bottom centre of each card.

**Card outline colours** indicate state. Because only one Generation Request may run per workflow at a time, this is never ambiguous:

| Outline | Meaning |
|---|---|
| None | Idle |
| Yellow | Currently running |
| Green | Finished — the outline clears once the user opens that workflow's video list |
| Red | An error occurred, accompanied by a pop-up explaining what happened |

Errors that the program can handle on its own — a request that succeeds on retry, a provider that responds slowly — are dealt with silently and do not produce a red outline. The red outline means something needs the user's attention.

A **refresh** control re-reads the workflows folder, so that a workflow edited while the application is open is picked up without restarting. This is needed constantly during development, when workflows are being written and adjusted while SFVF is running.

**Archived workflows.** If a workflow's code is deleted but its past output still exists, the card remains in a greyed-out archived state so that those videos stay browsable. This follows from separating code and output: deleting a plug-in should not destroy its history. Consequently the identifier in the manifest is permanent, because it is what links a workflow to its output folder, while the display name can be changed freely.

### 8.2 The Run pop-up

Opened by the Run Workflow button. It shows the workflow's own settings, rendered automatically from what the manifest declares, followed by the settings SFVF adds to every workflow, and then two buttons: **Cancel**, which closes the pop-up, and **Initiate**, which starts the run.

The settings SFVF supplies to every workflow:

| Setting | Purpose |
|---|---|
| Number of videos | How many videos this Generation Request produces. Capped where the workflow declares a maximum, and meaning either variants or episodes depending on what it declared (§5.1) |
| Budget | One line per active meter |
| Maximum retries | How many attempts a failing step gets before asking the user. Default 3. Set per Generation Request rather than globally, because what is worth retrying depends entirely on which steps a particular workflow has. |
| Concurrency | How many videos are produced at the same time. Ignored for a sequence workflow, which always runs one at a time |
| Parallel steps per video | How many independent units of work run at once *inside* a single video. Default 1 |
| Dry run | Runs the pipeline with fake assets and no spending |

**Why parallelism needs two settings rather than one.** The original setting answers "how many videos at once", which does nothing for a workflow producing one video composed of sixty independent generations — it would run them one after another and take hours against a provider willing to accept several at a time. The two axes are genuinely independent, and both are bounded underneath by the per-provider request queue, so raising either cannot flood a service.

Workflows may declare settings of these types: single-line text, multi-line text, number, yes/no, single choice from a list, multiple choice from a list, and file. The file type exists because some workflows take reference media as input — the planned animation-to-realism workflow needs a reference video before it can do anything.

Numeric settings are entered as numbers and validated before the run starts, with the unit shown beside the field rather than typed into it. Decimal values use a point rather than a comma, regardless of the machine's regional settings, because the same figures are written into the records and compared across runs.

**A choice list may be supplied by a provider instead of written into the manifest.** Two of the most important settings cannot sensibly be hard-coded. The narrator voice must include the user's own cloned voices, which exist only in their ElevenLabs account and change whenever they add one. The video model must reflect what Higgsfield currently offers, which is thirty or more models today and a different set next quarter. A manifest that lists either by hand is wrong the moment it is written.

So a workflow may declare that a choice list comes from a named provider source, and SFVF fills it in when the pop-up opens. The chosen value is still recorded as a pinned identifier, so the run remains reproducible even after the provider's catalogue moves on. If the provider cannot be reached, the last known list is offered with a note saying so, because being unable to start a run over a stale dropdown would be worse than the staleness.

Values used last time are remembered per workflow and pre-filled when the pop-up is reopened.

**Once a Generation Request starts, its settings are fixed.** The pop-up can still be opened from a running or paused workflow's card, but as a read-only view. This is not only about protecting the user from themselves: changing a parameter mid-run would change the cache keys of every step that reads it, so some videos in the request would be built one way and some another, with nothing in the record to show it. Changing settings means stopping the request and starting a new one.

**Initiate is blocked, with a specific message naming the problem**, if a required key or connection is missing, a required program is not installed, a capability the workflow declares it needs is not offered by any configured provider, provider balances are insufficient, or free disk space is below the hard floor. The point is that every one of these is knowable before starting, and discovering them mid-run wastes both time and money.

The capability check is the newest of these and the same argument applies to it exactly. A workflow whose whole approach depends on conditioning generation on reference images should not be allowed to research a topic, write a script and generate narration before discovering that the provider cannot do the one thing the workflow exists to do.

**Choosing the subject.** A workflow may offer a setting that lets the user either specify the topic or leave it to the research agent. Because all videos in one Generation Request share a topic, an AI-chosen topic is selected once, before any video is produced, rather than separately per video.

### 8.3 The video list

Clicking a workflow card opens a pseudo-tab — a view that is not one of the listed tabs, closed by a red button with a white cross in the top-right corner, which returns to the previous tab at the same scroll position it was left at.

It lists every video that workflow has produced, grouped by Generation Request, with a thin dividing line between groups. Videos can be played and deleted here.

Clicking a video opens a second pseudo-tab showing everything known about it: its status, its cost broken down by meter, the sequence of steps with how long each took and whether it reused a previous result, the exact rule and skill files that were in force for each agent including their contents, the provider and model choices that were made along with the alternatives considered, every intermediate file produced, and a **replay** view that reconstructs the run from its recorded timeline.

The replay is nearly free to build, because the events it needs are already being recorded with timestamps for other reasons. It exists because "why did this video come out like that" is a question that recurs constantly and is otherwise very hard to answer.

### 8.4 Schedule tab

Lists scheduled entries. Each entry pairs a workflow with a saved set of Generation Request settings, plus the days of the week and the time of day at which it should run.

- If a scheduled time arrives while the previous run of that workflow is still going, the scheduled run is skipped silently rather than queued. Queuing would cause runs to pile up unnoticed.
- If the budget is insufficient, the scheduled run is skipped silently.
- Each entry has a switch determining whether approval gates pause the run or are passed automatically. Without this switch, an unattended run that reaches an approval point at three in the morning would simply wait indefinitely, and every subsequent scheduled run would then be skipped because that one never finished.

### 8.5 Learning tab

Lists every workflow together with how many quality labels have accumulated since its last learning run. No minimum is imposed — the count is shown so the user can decide when there is enough to be worth acting on.

Starting a learning run for a workflow proposes changes to **that workflow's own rule and skill files only**. Global instruction files are never touched by an automated process. The reason is scope of consequence: a change to a global rule silently affects every workflow, including ones the user was not thinking about while reviewing, and there would be no obvious signal that it had happened. Global rules remain edited by hand.

The same outline colours are used as on the Main tab: yellow while the learning run is in progress, green when it has finished and is awaiting review, and the outline clears once the user accepts or rejects the proposals. On error, the outline turns red, a pop-up explains what happened, and the learning run reverts entirely to its state before it started, with no files modified. Errors the program can handle are dealt with silently.

Proposed changes are always reviewed before being applied. When accepted, the previous version of each modified file is archived rather than overwritten, so that the record of which instructions produced which past video remains meaningful.

### 8.6 Statistics tab

Spend over longer periods, with each meter displayed separately under the name of its provider. Real-currency providers are grouped together; credit providers are never combined with each other, for the reason given in §7.1.

### 8.7 Settings

- API keys and service connections, held in an encrypted file. The passphrase that decrypts it is requested when the application starts. **The encryption state is deliberately not shown in the interface.** It is not a mode the user chooses between, and because the passphrase is asked for before anything else is usable, an indicator would spend its whole life reporting the same value. Decryption is something that happens when it needs to, not something to be monitored.
- Connections that use MCP authenticate through a one-time login in the browser, after which only the resulting token is stored — never a password.
- Global defaults: how long a step may go without any sign of life before it is given up on, the default concurrency for both axes, the maximum size of the cache. **The step limit measures silence rather than elapsed time.** A step that is waiting on a provider reports that it is still alive, and the clock resets each time it does; a step that has genuinely hung reports nothing and is given up on. The distinction is not pedantic — a video generation may legitimately run for eleven minutes, and abandoning it means paying twice, once for the discarded job and once for the retry. A workflow may raise the limit for particular kinds of work where even silence is expected to be long. **Approval gates are excluded entirely.** A gate is waiting for a person, not doing work, and timing one out would mean an unattended run that reached an approval point at three in the morning failed rather than waited.
- Disk thresholds are fixed rather than configurable: a warning below 20 GB free, and a refusal to start new Generation Requests below 5 GB. A single run can consume two to three gigabytes, so 5 GB is roughly two runs of margin — enough to notice and act, not enough to run dry mid-render.

---

## 9. How runs behave

### 9.1 Isolation

Each video runs as a separate operating-system process, using that workflow's own isolated set of libraries.

This costs a little in complexity and buys three things that matter a great deal in a system of loosely-written plug-ins. Two workflows can depend on incompatible versions of the same library without ever colliding. A workflow that crashes or hangs cannot take the interface down with it. And cancelling a run is a reliable operation, because the whole process and anything it started can be terminated together.

Dependencies install themselves: SFVF records a fingerprint of each workflow's dependency list, and when that fingerprint changes it reinstalls before the next run, showing a brief preparing state. The user never has to think about it.

If a workflow requires a version of Python that is not installed on the machine, it is marked as blocked with an instruction to install that version.

### 9.2 Progress

Workflows report their own progress as a position, a total, and a description — "3 of 7, generating shots". SFVF does not impose a fixed set of stages, because pipelines legitimately differ from each other; a composition-based workflow and a generation-based one have genuinely different shapes, and forcing both into one vocabulary would make the display less informative rather than more.

**The total may change while a run is in progress**, and the display accommodates that rather than treating it as an error. A workflow that detects shot boundaries in a supplied reference video cannot know how many stages it has until it has looked, and fixing the total at whatever was reported first would produce a nonsense display for exactly the workflows that most need one.

Where a workflow runs many units of work in parallel inside one video, a second line reports how many of them have finished — "37 of 60 shots" beneath the stage description. Without it, a workflow would appear frozen on one stage for an hour.

### 9.3 Failure and retry

When a step fails, SFVF retries it up to the limit set for that Generation Request, defaulting to three attempts. If those are exhausted, a pop-up presents the recovery options that the workflow itself declared — for example switching to a cheaper video model — and the user either chooses one, retries the same option a chosen number of times, or aborts.

Recovery options are declared in the manifest rather than invented at the moment of failure, so that they are visible before starting rather than appearing as a surprise mid-run.

A failed video does not stop the other videos in its request. **Failures are expected and treated statistically**: the videos that succeeded are kept and used, the ones that failed are discarded, and the user starts another Generation Request if more are wanted. There is deliberately no button to regenerate an individual video, because the working assumption is that generation is unreliable and the correct response is to produce more and select, not to repair.

**A sequence workflow is the exception, and it has to be.** When videos are episodes, a failure cancels the ones after it rather than letting them continue, because they were to be built on state that now does not exist. The statistical argument does not apply to serial work: there is no selecting from among episode fours.

### 9.4 Stopping

Stopping is graceful. The step currently running is allowed to finish, its result is saved, and then the process exits. This matters because the step in progress has usually already been paid for — killing it immediately would waste money that has already left the account.

A second press of stop terminates the process immediately, losing everything after the last completed step.

### 9.5 Resuming

Restarting a stopped Generation Request re-enters the same folders. Steps that already completed return their saved results instantly, so execution continues from where it stopped.

Changing a workflow's version invalidates all of its remembered results. This is correct rather than inconvenient: if the code has changed, the results it produced before are no longer the results it would produce now, and reusing them would silently mix two different versions of the workflow inside one video.

**This does not touch the library.** Reusable assets are deliberately not version-scoped, because a typo fixed in a prompt must not discard the reference art the workflow has been accumulating for months. The two stores answer different questions — the cache asks "have I done exactly this work before", the library asks "do I already own this thing" — and only the first has any business caring which version of the code asked.

### 9.6 Automatic self-review

Before any video is presented as complete, SFVF checks it mechanically. None of this involves AI; it is all deterministic inspection:

- The file is valid and playable, with the expected duration and resolution.
- Frames sampled at several points are not black or visibly broken.
- The audio is neither silent nor distorted by clipping.
- Captions are present if the workflow said there would be captions.
- The video is not effectively a slideshow when it was supposed to contain motion, judged against a threshold appropriate to the declared format.
- Where the video was composed from a designed page: nothing is drawn outside the frame or beneath the platform's own interface, no text is clipped mid-word, and the fonts actually loaded.

These checks cost almost nothing and catch precisely the failures that otherwise waste the most time — a silent video, a black video, missing captions — because those are the failures you only notice after watching. A video that fails self-review is marked failed rather than presented as finished.

The last item was added because composed visuals fail in a way none of the others detect. When a page is written by an agent, a chart can end up positioned off the edge of the frame, a heading can be truncated, captions can sit under the buttons the platform draws, or a font can fail to load and render every character as an empty box. In all of these the file is valid, the frames are not black, the audio is fine, and the video is unusable. Since these are checkable by inspecting the page rather than the pixels, they are cheap enough that not checking would be the strange decision.

### 9.6a Approval gates

A workflow may pause and wait for the user before continuing. Gates exist to stop money being spent on a bad foundation, so they belong before expensive stages and not after: a gate placed after generation shows a receipt, while the same gate placed before it prevents the charge.

**A gate is not always a yes-or-no question.** Looking at eight character reference sheets of which one is wrong, "approve everything or abandon the run" is not the decision anyone wants to make. So a gate may also present a set of items — each with the image or clip in question — and let the user keep most of them, mark some to be redone, and write a note explaining what is wrong with them. That note is what the regeneration is told, and it is kept in the video's record.

**Anything a gate sends back must actually be redone.** This sounds obvious and is the single easiest thing to get wrong, because the system's default behaviour is to recognise identical work and return the previous result. A rejected asset regenerated with unchanged inputs would silently come back exactly as it was, which looks indistinguishable from a model ignoring the feedback. The rejection therefore forms part of what identifies the new attempt.

**Unattended runs need an answer in advance.** A scheduled run passes its gates automatically, and a workflow with gates that can do more than approve must state what the automatic answer is. The system will not invent one, because an invented default here means unrequested regeneration happening overnight.

---

## 10. Instructions: rules and skills

Rules are short and are always included in the prompt of the agent they target. Skills are longer and are referenced by path, so the agent reads them only when relevant. Both exist in two places: globally, applying to all workflows, and inside a specific workflow.

**Global and workflow-specific instructions are combined, not overridden.** When a workflow has its own rules for an agent, they are added to the global ones rather than replacing them. Ensuring the two do not contradict each other is the author's responsibility rather than something the system arbitrates, because any automatic resolution rule would be wrong roughly half the time and would hide the conflict rather than surfacing it.

Both rules and skills are targeted at particular agents using frontmatter, so that an agent writing a script is not being sent instructions about video editing on every single call. Without targeting, every agent receives every instruction, and the cost of that grows quietly with the size of the instruction library.

**Instructions are frozen per run.** At the start of every Generation Request, all the rule and skill files that apply are copied into that run's folder and recorded along with their content hashes and version numbers, grouped by agent. Editing a rule the following week therefore cannot retroactively change what a past run reports having used, and the interface can display the exact text that was in force when a given video was made. The files are small, so the storage cost is negligible against the debugging value.

---

## 10a. Reusable assets: the library

Some of what a workflow generates is worth keeping long after the run that produced it. A character's reference sheet, a recurring location's views, a style plate every episode is matched against: these cost real money, are made once, and are used for as long as the series runs.

Nothing else in this document can hold them. A run's folder belongs to one Generation Request. A workflow's folder is never written to while running. And the cache — the near miss — is keyed on the workflow's version precisely so that changing the code discards stale results, which is exactly the behaviour you do not want applied to forty euros of artwork.

So there is a fourth store. **The cache remembers work; the library holds things.**

### 10a.1 What makes an asset findable

Naming alone is insufficient, and this is the requirement that shapes everything else about the design. Real bodies of work accumulate near-variants — the same character in a different outfit, at a different point in the story, drawn for a different purpose — and a naming scheme that tries to encode all of that becomes a filing system nobody can query.

So every asset carries a **descriptor**: structured attributes the workflow defines, a written description of what the artefact actually is, and a record of its known defects. Selecting between assets is then a matter of reading text rather than looking at images.

That distinction is a cost decision, not a stylistic one. Showing every candidate to a vision model on every selection would make reuse more expensive than regeneration, which would defeat the purpose of keeping anything. Instead the attributes narrow three hundred assets to a handful for free, and only then does an agent read the descriptions and choose.

**Each asset is looked at exactly once, when it enters the library.** The description is written from the artefact rather than from the prompt that requested it, because generation drifts and a description written from intention is a plausible lie. One paid look, ever; every selection afterwards is free.

### 10a.2 Assets are identified by content, not by name

A name is a convenience that can be repointed; the identity that goes into a video's record is the hash of the file itself. This is what makes "which version of this character was in episode 7" answerable a year later, after the name has been repointed twice.

Nothing is ever overwritten. A redesigned asset is a new one that records what it supersedes, so current work finds the current version while old records still resolve to what they actually used. Nothing is deleted automatically, and manual deletion refuses to destroy anything a past run refers to.

### 10a.3 Small persistent state

The library also holds structured data, not only files — most usefully, where a series left off. A workflow producing one episode per Generation Request has no other way to know what happened last time, since everything else in this document is scoped to a single request.

### 10a.4 Shared between workflows, when they share a subject

A library belongs to a body of work rather than to a plug-in. Two workflows making short and long versions of the same series should draw on one set of characters, so a workflow names the collection it works with, defaulting to itself.

Copying assets from one collection to another is not offered as an alternative, and the reason is the identity rule above: a copy is a different file with a different identity, so the records of the two workflows would disagree about which reference was used while pointing at what is visibly the same picture.

---

## 11. Quality and learning

### 11.1 Quality factors

Each workflow declares its own set of quality factors, each phrased as a short question. **There are no numeric ratings anywhere in this system.**

For each finished video, the user writes a free-text answer to each factor. Then, for each factor, the user ranks that Generation Request's videos against one another. Separately, each video is marked accepted or rejected.

The design reasoning is worth stating, because "just score it out of ten" is the obvious alternative. Relative rankings within a single request are considerably more reliable learning data than absolute scores. Ranking three videos you have just watched against each other is a judgement people make consistently; assigning an absolute number is not, and the meaning of "7 out of 10" drifts over months as standards change. Ranking also avoids the problem of comparing a video made in August against one made in February under different instructions.

The consequence to be aware of is that learning value scales with how many videos each Generation Request produces. A request that produces one video yields answers but no ranking at all, since there is nothing to rank it against.

This falls hardest on sequence workflows, which produce one episode per request by design and therefore never rank. Their quality factors have to carry the whole signal on their own, so they should be written to elicit answers that name a specific failure and where it occurred, rather than answers that only mean something in comparison to an alternative.

All of this is stored inside the video's own record, so it travels with the run rather than living in a separate database that could drift out of alignment.

### 11.2 Learning runs

Learning is initiated manually, per workflow, from the Learning tab. A process derived from SkillOpt reads the accumulated answers, rankings and accept/reject decisions, together with the workflow's criteria files, and proposes bounded changes to that workflow's rule and skill documents.

Every proposal is reviewed by the user before anything is applied. This is not merely a safeguard: an automatically applied bad edit would degrade every subsequent video produced by that workflow, and there would be no visible signal that it had happened — the videos would simply get quietly worse. Review is the only point at which that can be caught.

Accepted changes increment the file's version and archive the previous one.

**Learning changes instructions and nothing else.** It may read anything as evidence — including the descriptions and known defects recorded against reusable assets, which are often exactly what explains a complaint about consistency — but it may only propose edits to that workflow's own rule and skill files. Global instructions are out of reach because a change there would silently affect workflows the user was not reviewing. The library is out of reach for a stronger version of the same reason: editing the description of a reference asset changes which assets get chosen in future, which changes what every subsequent episode looks like, through a chain of causation nobody would reconstruct from a small edit to a metadata file. Where the selection is going wrong, the thing to change is the instructions the selecting agent follows — which is inside the permitted set.

### 11.3 Criteria files

Criteria live in files inside the workflow's own folder, split by concern rather than kept as one long document, because what constitutes a good video differs substantially between workflow types. They are read by the learning process, not by the agents that produce videos.

---

## 12. Known constraints and risks

**Higgsfield clips are limited to about fifteen seconds.** Longer sequences must be built by chaining clips, using the last frame of one as the first frame of the next. Each shot is therefore its own step, so that a single unusable shot can be regenerated without repeating the others — which on a paid video model is a direct saving.

**Higgsfield's MCP tool surface is only partly known.** Higgsfield now publishes an official, OAuth-authenticated MCP server, which removes the earlier risk of depending on an unofficial community integration. What is still unconfirmed is the exact set of callable tools and their arguments, and Higgsfield also ships an official command-line client that fetches its model schema from the backend at run time rather than hard-coding it, which suggests the surface is expected to move. The design must therefore not assume any particular tool exists, and the provider integration stays isolated so that a different tool surface changes only that one module.

**HyperFrames fails quietly if its rules are broken.** Compositions must not read the real-world clock and must not use randomness without a fixed seed, because the renderer draws frames out of order and expects the page to look identical each time it is asked for a given moment. A composition that breaks these rules renders without any error and simply looks wrong. This must be stated explicitly in the graphics skill file, because silent failure is considerably worse than loud failure in a system where the code was written quickly.

**A headless browser needs fonts installed** or text renders as empty boxes with no error message. A small set of openly-licensed fonts is bundled and installed into the rendering environment.

**Disk space disappears quietly.** A warning appears below 20 GB free, and new Generation Requests are refused below 5 GB.

**Cache eviction differs by source.** Results from paid generation are never discarded automatically, because they were expensive and slow to produce. Renders and research results are discarded oldest-first once the cache exceeds its size limit, because they are cheap to reproduce. The library is not subject to eviction at all.

**Reference conditioning is assumed but not yet verified.** Two planned workflows depend on being able to condition a generation on supplied reference images or footage. Whether the provider supports this, and how well, is an open question that must be settled by experiment before that part of the provider integration is written. If it turns out to be unavailable, the approach to visual consistency has to change — which is far cheaper to discover before a library of reference art has been built around it than after.

**Consistent multi-view reference art may not be achievable.** A character turnaround whose views genuinely depict one character is a hard generation problem. If no reachable model does it well, what the library holds changes — many single-view references rather than one sheet — while the mechanism around it does not.

**Vocabulary drift in asset attributes is a silent, expensive failure.** An agent that writes one attribute name in March and a near-identical variant in November will find nothing, conclude the asset does not exist, and pay to regenerate something already owned. The system therefore requires attribute names to be declared in advance and rejects undeclared ones, normalises values mechanically, and reports the first appearance of any new value rather than quietly accepting it. It deliberately does not merge similar values automatically: a system that silently decides two names mean the same thing will eventually be wrong in a way nobody can see, which costs more than the occasional duplicate it would prevent.

**Time limits must measure silence rather than elapsed time.** A paid generation job can legitimately run for many minutes. Killing one because it exceeded a fixed limit means paying twice and discarding a result that arrives afterwards. The limit therefore counts time since the work last reported being alive, so a slow job survives and a genuinely hung one does not.

---

## 13. Planned workflows

**The example plug-in, shipping with version 1.** A composition-based workflow: research, then script, then a HyperFrames composition, then speech, then render. This is chosen deliberately as the first one because it is fast, deterministic and almost free to run, which means the plug-in interface can be exercised over and over while it is still unstable, without spending money on debugging the interface itself. A generation-heavy workflow would make every interface mistake expensive.

**A generation-based workflow.** Research, script, shot prompts, Higgsfield clips chained by first and last frame, speech, captions, assembly. Slow, expensive and non-deterministic — the case where remembering previous results matters most.

**Animation to realism (planned).** Reference animation clips are supplied as input. Shot boundaries are detected with PySceneDetect so that each shot can be handled separately. A vision-language model — an AI that can look at images and describe them in words — describes what happens in each shot, and those descriptions become generation prompts, with the source shot itself supplied as a reference where the provider supports it. B-roll shots are identified as such so they can be reproduced in kind. Character reference images are generated once, before any shot is produced, and kept in the library, so that character design stays consistent across the whole video and across later videos from the same source.

This workflow is the reason several features exist that would otherwise look speculative: file inputs in the settings, the shared preparation phase that runs once per Generation Request, progress totals that are not known until a run has begun, and the requirement that an uploaded file be identified by its contents rather than by where it happens to sit on disk.

**A serial character drama (planned).** Scripted episodes with a plot that develops across them, in a consistent animated style. Each episode is its own Generation Request; the story state is carried in the library, as are the character reference sheets and location views, which are generated once and reused indefinitely. Shots are written with deliberate cinematographic direction, generated with the reference art supplied as conditioning, and assembled into an episode.

This is the workflow that motivates most of what distinguishes version 2.3 from 2.2: the library itself, sequential rather than variant videos, atomic budgeting, forecasts, approval gates that can accept most of a set and reject part of it, parallel work inside a single video, and the acknowledgement that not every video is a forty-five-second vertical clip. It is also, by some distance, the most expensive thing planned here, which is why it should not be attempted until the cheaper workflows have exercised the interface thoroughly.

**A reference-driven workflow (planned).** Take an existing short-form video, analyse its pacing, hook and structure, and produce differentiated concepts on a new topic that reuse what made it work.
