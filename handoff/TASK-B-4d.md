# TASK B-4d — real `agents.research` over OpenRouter web search (mocked HTTP; NO live call)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`, `docs/`, or
`handoff/`. Two frozen contracts must BOTH stay green: the existing
`tests/integration/test_agents_openrouter_llm.py` (B-4c — do not regress it) and the new
`tests/integration/test_agents_openrouter_research.py`.

Wire the **non-dry** path of `agents.research` to OpenRouter's web search, reusing B-4c's HTTP plumbing. **Make
NO live network call** — the frozen tests use `httpx2.MockTransport`. `dry_run` stays exactly as today
(deterministic canned `Source` list, no network).

Files you may touch: `sdk/sfvf/agents.py` only.

## 1. Extract the shared chat-completion helper (keep `llm` behaviour identical)

Refactor the OpenRouter HTTP logic currently inline in `llm` into a private helper both functions use:

```python
def _post_chat_completion(ctx: Context, body: dict[str, Any]) -> dict[str, Any]:
    """POST /chat/completions with auth + rate limiting + retry; return the parsed 200 JSON.

    Reads the key via ctx.secret, builds the client via _http_client(), queues each attempt behind
    _LIMITER.slot("openrouter"); on 429 penalizes with the (validated) Retry-After and retries
    (bounded); 402 raises (insufficient credits); other non-2xx raises with status + body; returns
    resp.json() on 200. The bearer key is never logged or put in an error message.
    """
```

- Move `llm`'s existing request loop into this helper **unchanged in behaviour** — `llm` then builds its body
  and calls `data = _post_chat_completion(ctx, body)`, keeping cost surfacing and content parsing in `llm`.
  The B-4c `test_agents_openrouter_llm.py` (8 tests + the non-finite-Retry-After guard) MUST still pass.
- `_retry_after_s` and its `math.isfinite`/non-negative validation stay as they are.

## 2. Rewrite `research` (keep the signature and the dry-run branch)

```python
research(query) -> list[Source]
```

1. `ctx = current_context()` (unchanged — raises RuntimeError with no active context).
2. `if ctx.dry_run:` return the **existing canned `Source` list** (unchanged — no network, no secret read).
3. Non-dry:
   - `research` has **no model argument**, so use a pinned module constant, e.g.
     `_RESEARCH_MODEL = "openai/gpt-4o-mini"` (a real, pinned OpenRouter id — §6.1 requires a named model for
     reproducibility). Build the body:
     ```python
     body = {
         "model": _RESEARCH_MODEL,
         "messages": [{"role": "user", "content": query}],
         "plugins": [{"id": "web"}],   # OpenRouter web search
     }
     data = _post_chat_completion(ctx, body)
     ```
   - **Parse web results from the message annotations.** OpenRouter returns web results as
     `choices[0].message.annotations`, a list of `{"type": "url_citation", "url_citation": {"url", "title",
     "content", ...}}`. Map each `url_citation` entry to a `Source`:
     ```python
     message = data["choices"][0]["message"]
     sources: list[Source] = []
     for ann in message.get("annotations", []) or []:
         if ann.get("type") == "url_citation":
             c = ann["url_citation"]
             sources.append(Source(title=c.get("title", ""), url=c["url"], snippet=c.get("content", "")))
     ```
     Return `sources` (an **empty list** when there are no annotations — the frozen test checks this).
   - Surface cost via `ctx.log` exactly as `llm` does (read `usage.cost`; **no** `t=="cost"` event). `research`
     has no `agent`; log the model and cost.

No new dependency (httpx2 is already the `sfvf[openrouter]` extra). mypy-strict clean. Touch only `agents.py`.

## Acceptance

- `tests/integration/test_agents_openrouter_research.py` passes (5 tests): dry-run returns sources with no
  call; real maps `url_citation` annotations to `Source` and sends auth + a pinned model + the web plugin +
  the query; no annotations ⇒ empty list; missing key raises before any call; no-active-context raises.
- `tests/integration/test_agents_openrouter_llm.py` STILL passes (the helper extraction must not regress it).
- Nothing else regresses.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest -q tests/integration/test_agents_openrouter_research.py tests/integration/test_agents_openrouter_llm.py
```
(The full `pytest` run also shows the 3 pre-existing `finalize`/`example_workflow` failures — ONLY the
HyperFrames toolchain missing in this worktree; CI installs it and runs them green. Ignore them.)
