# TASK B-4c — real `agents.llm` over OpenRouter (mocked HTTP; NO live call)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`, `docs/`, or
`handoff/`. The reviewer contract `tests/integration/test_agents_openrouter_llm.py` is FROZEN.

Wire the **non-dry** path of `agents.llm` to OpenRouter's chat-completions API over `httpx2`. **Make NO live
network call** — the frozen tests replace the client with an `httpx2.MockTransport`. `dry_run` stays exactly as
today (deterministic stub, no network). `research` is a LATER increment — leave it as its current stub.

Files you may touch: `sdk/sfvf/agents.py`, `sdk/pyproject.toml`, `mypy.ini`. Do NOT change `_ratelimit.py`,
`context.py`, or the dry-run stub behaviour.

## OpenRouter contract (verified)

- `POST https://openrouter.ai/api/v1/chat/completions`, header `Authorization: Bearer <key>`.
- Request body: `{"model": <model>, "messages": [{"role":"user","content": <prompt>}]}`; when `schema` is given
  add `"response_format": {"type":"json_schema","json_schema":{"name":"result","strict":true,"schema":<schema>}}`.
- Success 200: `choices[0].message.content` (a string; when a schema was requested it's a JSON string — parse
  with `json.loads`). `usage` may include `prompt_tokens`/`completion_tokens`/`total_tokens` and an optional
  `cost` (USD).
- Errors: `{"error":{"code","message",...}}`; **429** rate-limited (honor `Retry-After`), **402** insufficient
  credits (terminal).

## Seams the tests require (implement exactly)

- `def _http_client() -> httpx2.Client:` — module-level factory; **lazy-import `httpx2` inside it** and return
  `httpx2.Client(base_url="https://openrouter.ai/api/v1", timeout=<sane>)`. The real path builds its client
  ONLY through this. If `httpx2` is missing, raise a clear `RuntimeError` naming the `sfvf[openrouter]` extra.
- `_LIMITER` — a module-level name bound to the shared limiter: `from ._ratelimit import LIMITER as _LIMITER`
  (rebindable, so tests can swap in a fake-clock limiter). Configure the `"openrouter"` queue once
  (e.g. `_LIMITER.configure("openrouter", max_concurrency=<small>, min_interval_s=<small-or-0>)`) — do it at
  import time or lazily-once (mind HARDENING H8: configure before first use, never mid-flight).

## Rewrite `agents.llm` (keep the signature and the dry-run branch)

```python
llm(prompt, *, agent, model, schema=None, attach=None) -> str | dict
```

1. `ctx = current_context()` (unchanged — raises RuntimeError with no active context).
2. **`if ctx.dry_run:`** return the existing deterministic stub (unchanged — schema→`_dict_for_schema`,
   else the stub string). **No network, no secret read, no HTTP client.**
3. Non-dry:
   - `if attach:` raise `NotImplementedError("agents.llm vision attachments are not yet supported by the "
     "OpenRouter adapter")` — do NOT silently ignore attachments (SDK §6.1).
   - `key = ctx.secret("OPENROUTER_API_KEY")` (a missing key raises `KeyError` here, BEFORE any client is
     built or request sent — the frozen test asserts no call is made).
   - Build the request body per the contract above (user message = `prompt`; `agent` is accepted and may be
     recorded, but agent-rules injection is OUT OF SCOPE this increment — a later increment).
   - **Retry loop (max 3 attempts), each attempt inside a fresh limiter slot:**
     ```
     for attempt in range(3):
         with _LIMITER.slot("openrouter"):
             resp = client.post("/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
         if resp.status_code == 200: break
         if resp.status_code == 429:
             _LIMITER.penalize("openrouter", <Retry-After seconds, default e.g. 1.0 if absent/unparseable>)
             continue
         if resp.status_code == 402: raise RuntimeError("OpenRouter: insufficient credits (402)")
         raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text}")
     else: raise RuntimeError("OpenRouter: rate limited after retries (429)")
     ```
     Build the client via `_http_client()` (use it as a context manager / close it). Parse `Retry-After` as a
     number of seconds; on a missing/garbage value use a small default.
   - Parse the 200 body: `content = data["choices"][0]["message"]["content"]`. If `schema` is not None, return
     `json.loads(content)` (a dict); else return `content` (a str).
   - **Cost surfacing (NO cost event):** read `data.get("usage", {}).get("cost")`. Surface it via
     `ctx.log(...)` — a single structured info line including the model and the cost (real value, or `None`/an
     estimate). **Do NOT emit any event whose `t == "cost"`** — the budget-engine cost/meter schema is Stage
     C's (HARDENING). A `ctx.log` message that contains the cost figure is what the test checks for.

## `sdk/pyproject.toml` / `mypy.ini`

- Add an optional extra: `[project.optional-dependencies] openrouter = ["httpx2==2.10.0"]` (exact pin; matches
  `requirements-dev.txt`, so the gate already has it). Keep core `dependencies` unchanged.
- If mypy can't find `httpx2` stubs, add `[mypy-httpx2.*] ignore_missing_imports = True` to `mypy.ini` — only
  if needed. Do not loosen strictness elsewhere.

## Acceptance

- `tests/integration/test_agents_openrouter_llm.py` passes (8 tests): dry-run makes no call + returns a stub;
  real request carries the Bearer auth + model + messages and returns the content; schema returns a parsed
  dict + sends `response_format` json_schema; a 429 honors `Retry-After` (via the limiter) then succeeds; a 402
  raises without retry; the real `usage.cost` is surfaced in a log line while NO `cost` event is emitted; a
  missing key raises before any call; no-active-context raises.
- No live network call anywhere. `research` and the dry-run stubs are unchanged. Nothing else regresses.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_agents_openrouter_llm.py
```
(The full `pytest` run also shows the 3 pre-existing `finalize`/`example_workflow` failures — ONLY the
HyperFrames toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
