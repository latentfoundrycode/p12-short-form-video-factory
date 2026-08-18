# Short-Form Video Factory (SFVF)

A chassis for running user-authored **workflows** that generate short-form videos.

You write a small Python workflow; SFVF handles everything around it — isolated
environments, run bookkeeping, subprocess orchestration, live progress, and (coming soon)
an API and browser UI. Workflows never touch the chassis internals: they talk to it through
a tiny SDK context object and a line-based event protocol.

> **Status:** under active development. Stage 2 (Execution) is mostly complete — run
> scaffolding, environments, the runner + event protocol, and the supervisor are in place.
> The HTTP API and web UI for starting runs are the next milestone. See [Roadmap](#roadmap).

---

## How it works

```
 workflow.toml + your code
            │
            ▼
   ┌─────────────────┐   creates run folder, ensures an isolated venv,
   │   Supervisor    │   runs preparation once, then launches video
   └─────────────────┘   subprocesses (up to your concurrency)
            │
            ▼
   python -m sfvf.runner  ──►  your entrypoint(ctx)
            │                         │
            │   JSON-Lines on stdout  │  ctx.emit / log / stage / heartbeat …
            ▼                         ▼
   events.jsonl + request.json + video.json   (everything durable, per run)
```

A workflow is just a folder with a `workflow.toml` manifest and an entrypoint function. The
supervisor prepares an isolated virtual environment for it, optionally runs a one-time
**preparation** step, then runs one or more **video** subprocesses. Each subprocess streams
structured events to stdout; the chassis records them and drives live status. All run state
lives in files on disk, so nothing important is lost if the backend restarts.

## Repository layout

| Path | What's there |
|------|--------------|
| `app/` | The chassis backend (FastAPI). |
| `app/core/` | Run scaffolding, environment manager, event tolerance, supervisor, process control. |
| `app/registry/` | Workflow discovery, manifest schema, and validation. |
| `sdk/sfvf/` | The workflow-facing SDK: the runner, the context object, and the emit helpers. |
| `frontend/` | The web UI (Vite + React). |
| `tests/` | Test suite and test-only stub workflows. |
| `docs/` | Architecture, requirements, SDK guide, and UI mockup. |
| `runs/`, `venvs/` | Runtime output and per-workflow environments (git-ignored). |

## Getting started

**Requirements:** Python 3.12 and Node.js (for the frontend).

```bash
# 1. Clone
git clone https://github.com/latentfoundrycode/short-form-video-factory.git
cd short-form-video-factory

# 2. Python environment (installs the SDK in editable mode too)
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt

# 3. Frontend dependencies
npm --prefix frontend install
```

## Writing a workflow

A workflow lives in its own folder with a manifest and an entrypoint:

```toml
# workflow.toml
[workflow]
id = "my-workflow"
name = "My Workflow"
version = "1.0.0"
entrypoint = "main:run"     # file:function
prepare = "main:prepare"    # optional, runs once before videos
python = "3.12"
video_semantics = "variants"  # or "sequence"
atomic = false

# optional per-step silence limits (seconds without output before a step is killed)
[[limits]]
step = "render"
seconds = 600
```

```python
# main.py
def run(ctx):
    ctx.stage(1, 2, "start")
    ctx.log("doing the work")
    ctx.heartbeat("render", waiting_on="encoder")
    ctx.emit({"t": "result", "video": "final.mp4", "caption": "hello"})
```

Everything the workflow needs (validated settings, the paths it should use, preparation
output) is handed in through `ctx`. Everything the workflow reports goes out as one JSON
object per line on stdout — anything that isn't valid JSON is captured as a plain log line,
so ordinary `print`s and library output are never lost.

## Development

Run the full check gate before committing — all six must pass:

```bash
ruff check .
ruff format --check .
mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
pytest
```

The test suite drives the runner and supervisor against small stub workflows in
`tests/stubs/`, so no real video tooling or network access is needed to develop the chassis.

## Roadmap

- ✅ **Run scaffolding** — run IDs, folder layout, atomic records IO.
- ✅ **Environment manager** — isolated per-workflow venvs, dependency-hash reinstalls.
- ✅ **Runner + event protocol** — the subprocess contract and JSON-Lines events.
- ✅ **Supervisor** — preparation, concurrency, silence-based time limits, graceful/hard stop.
- ⬜ **Run API + live progress** — start/stop over HTTP, live updates to the browser grid.
- ⬜ **End-to-end wiring** — the full path from the UI through to finished videos.
- 🔜 **Later stages** — budgets, approval gates, caching, and quality capture.

## License

See the repository for license details.
