# TASK-SSN-C2 — Research pool + pick N distinct subjects in prepare()

## Context

You are the builder for the Sensational Science News (SSN) workflow. C1 scaffolded the workflow
(`workflows/sensational-science-news/`); `prepare()` currently returns placeholder subjects. This
task makes `prepare()` do the real subject-selection: query the research agent restricted to the
owner's curated science-news allowlist, pick N captivating, distinct, non-repeating subjects (N =
`ctx.video_count`), record them so future runs don't repeat them, and return them for the per-video
`run()` calls.

`prepare()` runs ONCE per generation request, before the parallel per-video workers. It selects ALL
N subjects in one pass. `run(video_index)` already consumes `ctx.shared["subjects"][video_index - 1]`
— DO NOT change that contract.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Do NOT modify: any test, any SDK file, any other workflow file, `workflow.toml`, `requirements.txt`,
or dependencies. Do not add imports beyond the standard library and what `main.py` already imports
(`from sfvf import Context, Result, agents, media`; plus `json`, `re`, `html`). `urllib.parse` from
the standard library is allowed and expected.

## Workspace boundary

You may read and write only inside this checkout (`Workspace/`). Never touch anything outside it.

## The SDK you will use (already available; do not re-implement)

- `agents.research(query: str) -> list[Source]` — `Source` is a TypedDict `{title, url, snippet}`.
  You control the query; put `site:` hints in it for the allowlist. It returns whatever the model
  cites — you MUST post-filter the results to the allowlist yourself (below); the query hint is not
  a guarantee.
- `agents.llm(prompt, *, agent, model, schema=None, attach=None)` — returns a `dict` when `schema`
  is a JSON-schema dict, else a `str`. Use `model=_LLM_MODEL`, `agent="subject-picker"` (or similar).
- `ctx.video_count` (int, = N), `ctx.dry_run` (bool).
- `ctx.step(family, *, inputs=...) as step:` — wrap the selection work in the existing
  `"choose-subjects"` step (keep it). `step.value` / `step.set(...)` / `step.cached` as in C1.
- Cross-run dedup list is a **library value asset** named exactly `"used-subjects"`:
  - read:  `ctx.library.value("used-subjects")` → the stored JSON `list[str]`, or `None` if never set.
  - write: `ctx.library.put("used-subjects", <new_list>, kind="value")` — the list is the SECOND
    POSITIONAL argument (there is NO `data=` kwarg; a non-`Path` second arg is stored as JSON).
  - `ctx.library` may be `None` in principle; guard it (`if ctx.library is not None`). In these runs
    it is present.

## What to build

### 1. The allowlist (module constant)

Add a module-level constant for the owner's trusted science-news sites, as `(host, path_prefix)`
pairs. `path_prefix=""` means the whole host is allowed; a non-empty prefix means only URLs whose
path starts at that path boundary are allowed. Derive it from these owner-provided sites (note two
`reuters.com` entries with different path prefixes, and `news.mit.edu` is a specific subdomain host):

```
sciencenews.org            ""
science.org                ""
sciencedaily.com           ""
nature.com                 ""
scientificamerican.com     ""
bbc.com                    "/news/science_and_environment"
phys.org                   ""
sci.news                   ""
livescience.com            ""
npr.org                    "/sections/science"
cbc.ca                     "/news/science"
snexplores.org             ""
newscientist.com           ""
reuters.com                "/science"
bloomberg.com              "/ai"
news.mit.edu               ""
reuters.com                "/technology"
```

### 2. `_allowlist_filter(sources) -> list` (pure helper — a frozen test calls it directly)

Keep every source whose URL matches an allowlist entry, drop the rest, preserving order. Matching:

- Parse the URL with `urllib.parse.urlparse`. Compare the **host**, not a substring: normalise both
  the candidate host and the entry host by lower-casing and stripping a leading `www.`, then require
  **host equality** (so `evil.example.com/nature.com/...` does NOT match `nature.com`). Do NOT strip
  `news.` — `news.mit.edu` is its own host.
- For an entry with a non-empty `path_prefix`, additionally require the URL path to match at a path
  boundary: `path == prefix` or `path.startswith(prefix + "/")` (so `/news/science_and_environment/z`
  matches but `/sport/football` and a hypothetical `/news/science_and_environmentX` do not).
- An entry with `path_prefix == ""` matches any path on that host.

The function takes the list of `Source` dicts and returns the filtered list of `Source` dicts.

### 3. Rewrite `prepare(ctx)`

Inside the existing `with ctx.step("choose-subjects", inputs={"count": ctx.video_count}) as step:`
block (compute only when `not step.cached`), do:

1. Build a research query that names the allowlist hosts with `site:` hints and asks for recent,
   captivating science-news stories, and call `agents.research(query)`.
2. `pool = _allowlist_filter(results)`. If the pool has fewer than N on-allowlist sources, BROADEN
   once: issue a second, less-restricted `agents.research(...)` query and re-filter, then keep the
   union (deduped by URL). (One broaden attempt is enough.)
3. Determine the empty-pool outcome:
   - If the on-allowlist pool is still empty:
     - when `ctx.dry_run` is True → fall back to the RAW research results as the pool so the dry-run
       pipeline can still rehearse (dry-run research returns off-allowlist canned sources; a
       rehearsal must not hard-fail here).
     - when `ctx.dry_run` is False → `raise RuntimeError(...)` with a clear message. NEVER fabricate
       a subject on a real run.
4. Read the cross-run dedup list: `used = set(ctx.library.value("used-subjects") or [])`.
5. Ask `agents.llm(...)` with a JSON `schema` of the shape
   `{"type":"object","properties":{"subjects":{"type":"array","items":{"type":"string"}}},
   "required":["subjects"]}` to score the pool for lay-audience CAPTIVATION (entertainment value
   first, per the workflow's editorial rules) and return its ranked chosen subjects as
   `result["subjects"]` (a `list[str]`). Give it the pool (titles + snippets) and the `used` list as
   context.
6. Enforce the guarantees WORKFLOW-SIDE (do not trust the model to have obeyed):
   - drop any chosen subject that is in `used` (cross-run dedup),
   - drop duplicates among the chosen (case-insensitive is fine), preserving order,
   - take the first N.
   - If fewer than N remain, BACKFILL from the pool's own source titles (those not in `used` and not
     already chosen, distinct) until you have N or the pool is exhausted. This backfill is what makes
     the dry-run rehearsal yield N distinct subjects even when the LLM stub is unhelpful.
7. `chosen` (the final `list[str]`, length ≤ N) is the result. Append it to the dedup list and write
   it back: `ctx.library.put("used-subjects", sorted(set(used) | set(chosen)), kind="value")` (guard
   `ctx.library is not None`). Store `chosen` via `step.set(...)` so it is cached.
8. Build a best-effort `sources` mapping `dict[str, list[Source]]` — for each chosen subject, the
   on-allowlist source(s) it was drawn from (match by title when possible; otherwise attach the
   filtered pool). It only needs to be JSON-serialisable and present.

Return `{"subjects": <chosen list>, "sources": <sources mapping>}`. (The runner stores this as
`ctx.shared`; `run()` reads `ctx.shared["subjects"]`.)

Keep `run()` unchanged except that it may now also read `ctx.shared.get("sources")` if convenient —
but no run()-side behaviour change is required in this task.

## Done when

All of these pass (run from `Workspace/` with the repo venv):

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_prepare.py -q` — all 4 pass:
  - `test_allowlist_filter_keeps_on_list_drops_off_list`
  - `test_prepare_selects_n_distinct_subjects`
  - `test_prepare_excludes_cross_run_dedup_list`
  - `test_prepare_empty_on_allowlist_pool_fails_cleanly`
- `./.venv/Scripts/python.exe -m pytest tests/registry/test_ssn_workflow.py tests/integration/test_ssn_workflow_dry_run.py -q` — still green (the C1 dry-run pipeline still produces a finished video and N subjects).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` — clean.
- `./.venv/Scripts/python.exe -m ruff format --check .` — clean (run `ruff format` on the file if needed).
- `./.venv/Scripts/python.exe -m mypy` — no new errors in `main.py`.

Print the final `prepare()` and `_allowlist_filter()` you wrote, and one line each on: how you
broaden, and how the dry-run fallback keeps the rehearsal from hard-failing.
