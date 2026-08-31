# TASK-005-2 — Live event stream over SSE (with catch-up)

## One-line task and why
Add a Server-Sent-Events endpoint that turns a run's `events.jsonl` into a live browser
stream: it first replays the whole file (so a late-joining or reconnecting client is brought
current), then tails new events live, and closes when the run finishes. This is the
reconnect-from-`events.jsonl` path the Architecture calls out (§3.3: "that single file is the
entire input to the replay view"; §1.2 SSE; §6 "Live state arrives over a single Server-Sent
Events connection"). Second increment of Task 5. File/range serving is 005-3 (OUT of scope here).

## Context you need (read before coding)
- `app/api/runs.py` — the existing run router built in 005-1 (`/api/workflows/{id}/runs...`
  endpoints, `_require_workflow`, `_runs_dir(request)`, `is_safe_path_segment`). Add the new
  endpoint HERE, in the same style.
- `app/core/records.py` — `read_events(run_dir) -> Iterator[tuple[ts, source, event]]`. It reads
  the whole file and **stops cleanly at the first torn/invalid line** (a crash mid-append leaves a
  truncated last line). USE THIS to read events; do not re-parse the file yourself.
- `app/main.py` — `create_app(...)` already injects `runs_dir` onto `app.state`; reuse
  `_runs_dir(request)`.
- Run lifecycle: the supervisor appends events under a per-run lock and only writes the terminal
  `request.json` status (`complete`/`partial`/`stopped`/`stopped-budget`/`failed`) after all
  videos finish — so when the request status is terminal, every event is already in the file.

## Third-party surface — VERIFIED, use as written (do not add dependencies)
- SSE is plain `text/event-stream`; implement with Starlette's `StreamingResponse` (already
  available via FastAPI). Do **not** add `sse-starlette` or any new dependency.
- The test client is Starlette's `TestClient`, backed by **httpx2** (the Pydantic-maintained
  successor to httpx; `import httpx2 as httpx` inside Starlette). Its streaming API mirrors httpx:
  `with client.stream("GET", url) as response: for line in response.iter_lines(): ...`. Use that
  for the SSE tests. `httpx2` is already a project dev dependency — do not touch requirements.

## Endpoint
`GET /api/workflows/{workflow_id}/runs/{run_id}/events` → `media_type="text/event-stream"`.

Behaviour, precisely:
1. Validate `workflow_id`/`run_id` with `is_safe_path_segment` and the registry (reuse
   `_require_workflow`); unsafe/unknown → 404.
2. **Tolerate a just-created run.** 005-1's `on_started` fires just before `request.json` is
   written, so a client that subscribes immediately after the 202 may arrive before the file
   exists. If `<runs_dir>/<workflow_id>/<run_id>/request.json` is not present yet, wait for it up
   to a small bounded time (~2s, polling ~50ms); if it still does not appear, 404. (A run that
   truly never existed 404s after that brief wait.)
3. **Stream envelopes.** Emit each `events.jsonl` entry as one SSE message:
   `data: <json>\n\n`, where `<json>` is the envelope `{"ts":..., "source":..., "event":...}`
   (rebuild it from the `read_events` tuple with `json.dumps(..., ensure_ascii=False)`). One
   message per event. No other SSE fields are required.
   - **Catch-up first:** emit every envelope already in the file (via `read_events`).
   - **Then live-tail:** keep emitting envelopes appended after those, in order. Track how many
     you have already emitted (a simple count) and re-read with `read_events`, skipping the ones
     already sent. Re-reading the whole file each poll is O(n); that is acceptable at this stage
     (matches the existing fsync-per-event note) — do not build a byte-offset tailer.
   - **Poll interval** ~0.25s between reads while the run is live.
4. **Terminate cleanly.** End the stream when the run's `request.json` status is terminal AND no
   unemitted envelopes remain — do one final `read_events` drain after observing a terminal
   status, emit any stragglers, then stop the generator. Also stop if the client disconnects
   (check `await request.is_disconnected()` each poll). A run that is already finished when the
   client connects therefore yields the full history and then closes (pure replay).

Use an **async generator** with `asyncio.sleep` for the poll (do not block the event loop with
`time.sleep`). Keep the generator's own state local; keep no authoritative run state in memory
(§15) — everything comes from the files.

## TDD-first — write failing tests before the implementation
Add tests (extend `tests/api/test_runs.py` or a new `tests/api/test_run_events.py`; match the
existing fixtures — the autouse supervisor-state cleaner, `_ready`, `_install_stub`, `_client`).
Cover at least:
- **Replay of a finished run (deterministic):** run a `succeeds` run to completion (launch via the
  API and `_wait_terminal`, or drive `run_request` directly), THEN open the SSE stream and collect
  all `data:` payloads via `client.stream(...).iter_lines()`. Assert the parsed envelopes include
  the known events (e.g. a `log` "ok" and the `result`) in file order, and that the stream closes
  on its own (iteration ends).
- **Catch-up then live to terminal:** start a run, open the stream while it is running, collect
  until the stream closes; assert it ends and the collected events include the run's final events.
  Keep it bounded (a fast stub like `succeeds`/`cooperates`).
- **Unknown run → 404** (after the bounded wait).
- (Optional but nice) **torn last line tolerated:** append a half-written line to a finished run's
  `events.jsonl` and assert the stream still replays everything up to it and closes.

Confirm the tests fail first (no endpoint), then implement until green.

## Scope — files you may change
- `app/api/runs.py` (add the endpoint + the streaming generator helper)
- `tests/api/test_runs.py` and/or `tests/api/test_run_events.py`

## Do NOT touch
- `app/core/*` (supervisor, records, events, proc), `app/registry/*`, the SDK (`sdk/`), the
  frontend (`frontend/`), `app/main.py` (the injection you need already exists), or anything under
  `docs/` or `handoff/`.
- Do NOT add dependencies (no `sse-starlette`, no `httpx`—`httpx2` is already present).
- Do NOT add file/range serving (that is 005-3). Do NOT keep authoritative run state in memory.

## Gate — run all six before committing (worktree root, PowerShell)
```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```
All clean. Report the final pytest count (138 + your new tests).

## Commit message (house style — imperative subject stating change and rationale)
```
Stream a run's events over SSE, replaying events.jsonl on connect so a late-joining or reconnecting client is brought fully current before live tailing.
```
(Cursor appends its `Co-authored-by` trailer automatically.)

## Report back
Print the files changed, the commit hash, and the final pytest count.
