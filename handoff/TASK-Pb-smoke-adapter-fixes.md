# TASK-Pb-smoke-adapter-fixes: Correct BFL polling-URL and MiniMax default resolution

## Objective
The Stage P-B attended live smoke (2026-09-20) exposed two provider-adapter bugs that
the mock unit tests missed, because each mock happened to match the adapter's own wrong
assumption. Two frozen RED contracts already exist and currently FAIL:
`tests/integration/test_provider_live_fixes.py::test_bfl_polls_the_regional_polling_url`
and `::test_minimax_sends_a_default_resolution`. This increment makes BOTH pass by
editing exactly two source files so the adapters do what the real providers require:
BFL must poll the regional `polling_url` the submit response returns, and MiniMax must
always send a `resolution` parameter (defaulting when the caller supplies none). No
behaviour beyond these two corrections changes.

## Scope
Files you may modify:
- sdk/sfvf/providers/bfl.py
- sdk/sfvf/providers/minimax.py

Do not modify anything else.

## Out of scope
- Any test file, including `tests/integration/test_provider_live_fixes.py` and every
  file under `tests/` — they are FROZEN.
- Any other file under `sdk/` (helpers in `_http.py`, `_poll.py`, `base.py`, etc.).
- workflows/, app/, docs/, handoff/
- requirements files, CI configuration
- .env and anything under secrets/

## Context
This is a logic / data-access increment against external provider APIs. The trust
boundary is the outbound HTTP call to each third-party provider; the smoke proved the
adapters were sending requests the providers reject. `.cursor/rules/secure-coding.mdc`
is in force. No secret values appear in this brief or belong in code — API keys are read
from `secrets["BFL_API_KEY"]` / `secrets["MINIMAX_API_KEY"]` as the existing code already
does; refer to them by name only.

The frozen contracts (read them, do not edit them) are in
`tests/integration/test_provider_live_fixes.py`. Their docstring records exactly why each
adapter was wrong and what the live smoke observed.

### BFL — `sdk/sfvf/providers/bfl.py`
The relevant function is `_submit_poll_download(client, auth, path, body)` (lines ~38-71).
Today it does:
```python
submit = request(client, "POST", path, provider="bfl", auth=auth, limiter=LIMITER, json=body)
task_id = parse_json(submit, provider="bfl", where="submit")["id"]
...
payload = poll_until(
    client,
    method="GET",
    path=f"/v1/get_result?id={task_id}",
    ...
)
```
The submit JSON also returns a `polling_url` — an ABSOLUTE URL on a possibly-regional
host (e.g. `https://api.us1.bfl.ai/v1/get_result?id=...`). The result is only retrievable
there; polling the hardcoded path on the global submit host returns 404 "Task not found"
(the exact live failure). `request()` / `poll_until` pass `path` straight to the httpx2
client, which honours an absolute URL regardless of the client `base_url`, so passing the
absolute `polling_url` as `path` needs no other change. The `AdapterError` type is already
imported from `.base`. The P-6 spec (`docs/PROVIDER_LAYER_PLAN.md`, ~line 330) already says
"poll `polling_url`"; this aligns the code with the spec.

### MiniMax — `sdk/sfvf/providers/minimax.py`
The relevant function is `generate_video(...)` (lines ~29-93). Today it builds:
```python
body: dict[str, Any] = {"model": model.slug, "content": content}
if duration_s is not None:
    body["duration"] = round(duration_s)
body.update(extra or {})  # resolution / ratio passthrough
```
MiniMax's `POST /v2/video_generation` REQUIRES a `resolution` parameter; when the caller
passes no `extra`, the body carries none and MiniMax returns 400 ("missing required
parameter ... resolution"). A default must be present while still letting an explicit
`extra["resolution"]` win.

## Requirements
1. In `sdk/sfvf/providers/bfl.py`, `_submit_poll_download`: parse the submit JSON once,
   read `polling_url` from it (the response also carries `id`, but the poll must use
   `polling_url`).
2. If `polling_url` is missing or empty, raise
   `AdapterError("bfl", where="submit", detail="no polling_url in submit response")`.
3. Pass that absolute `polling_url` as the `path` argument to `poll_until(...)` in place
   of the hardcoded `f"/v1/get_result?id={task_id}"`. Do not change the `_done`
   terminal-status logic, the `result.sample` extraction, or the download.
4. In `sdk/sfvf/providers/minimax.py`, define a module-level constant
   `_DEFAULT_RESOLUTION = "768P"` (a valid documented value; the valid set is
   "480P" / "768P" / "2K").
5. After `body.update(extra or {})`, add `body.setdefault("resolution", _DEFAULT_RESOLUTION)`
   so an explicit `extra["resolution"]` still wins but a default is always present. Change
   nothing else in the function.

## Acceptance criteria
- [ ] `python -m pytest tests/integration/test_provider_live_fixes.py` — both
      `test_bfl_polls_the_regional_polling_url` and `test_minimax_sends_a_default_resolution`
      pass.
- [ ] `python -m pytest tests/integration/test_image_bfl.py tests/integration/test_video_minimax.py`
      — the existing frozen P-6/P-7 contracts still pass (no regression).
- [ ] `ruff check`, `ruff format --check`, and `mypy` are clean on
      `sdk/sfvf/providers/bfl.py` and `sdk/sfvf/providers/minimax.py`.
- [ ] `git diff` shows exactly those two files changed, and nothing else.
- [ ] No new Semgrep high findings; no secret value appears in the diff.

## Constraints
- Do not add dependencies.
- Do not read or write any file outside this workspace (the folder you were started in).
  Everything you need is inside it; everything you produce goes inside it.
- Minimal change (the frozen `minimal-code.mdc` is in force): make the smallest edits that
  turn the two contracts green. Do not refactor the surrounding functions, rename things,
  or "improve" anything you notice along the way.
- Do not edit any test file. The two failing contracts and the P-6/P-7 contracts are frozen.
- Follow existing conventions in the two files you touch (the `AdapterError(...)` call
  shape, `from __future__ import annotations`, existing typing style).
- If the brief, the rules, or the tooling got in your way, append one dated line describing
  it to `docs/BUILDER_NOTES.md`. Do not try to fix the tooling. (This is the only file
  outside scope you may append to, and only for that purpose.)

## Done
Print the list of every file you changed and a one-paragraph summary of what you did.
