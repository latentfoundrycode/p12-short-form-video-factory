# TASK A-3 — `sfvf.agents` dry-run stubs (LLM + research)

**Builder:** Cursor. **Product code only.** Do NOT modify, add, or delete anything under `tests/`
(including `tests/stubs/`), `docs/`, or `handoff/`. The reviewer contract `tests/sdk/test_agents.py` is
FROZEN — make it pass by changing product code.

Third increment of **Stage A**. Adds the `sfvf.agents` surface (SDK §6.1) with dry-run stub
implementations, so a workflow's language-model and research steps run for free while the pipeline is
built. The real OpenRouter adapter is Stage B; here the non-dry path raises.

Files you may touch: `sdk/sfvf/agents.py` (new), `sdk/sfvf/__init__.py`. Do not add dependencies.

## 1. `sdk/sfvf/agents.py` (new)

```python
llm(prompt, *, agent, model, schema=None, attach=None) -> str | dict
research(query) -> list[Source]
```

- `Source` — a **`TypedDict`** (from `typing`), not a dataclass: `class Source(TypedDict): title: str;
  url: str; snippet: str`. It must be JSON-serializable at runtime (a plain `dict`), because the documented
  pattern caches research results via `ctx.step` and **step results must be JSON-serializable** (SDK §5.5).
  A rich object (dataclass) would raise `TypeError` in the step cache's `json.dump`.
- Both functions read the ambient Context via `from ._runtime import current_context` to decide dry-run —
  they are **not** passed `ctx`. `current_context()` already raises if called outside a running workflow,
  which is the required "requires an active context" behaviour (do not catch it).
- **Dry-run** (`current_context().dry_run` is true):
  - `llm(...)` with `schema is None` → a **deterministic**, non-empty placeholder **string** (a pure
    function of its inputs — e.g. derived from `agent`/`model`/`prompt`; no RNG, clock, or `id()`). The
    same inputs must return the same string.
  - `llm(...)` with `schema` given → a **deterministic** `dict` that **reflects the schema** so a workflow
    reading structured fields can be exercised in dry-run. Treat `schema` as JSON-schema: if it has a
    `"properties"` mapping, return one key per property with a typed placeholder by the property's `"type"`
    (`"string"`→a placeholder str, `"integer"`/`"number"`→`0`, `"array"`→`[]`, `"object"`→`{}`,
    `"boolean"`→`False`, else a str). If there are no recognisable properties, return a generic
    `{"text": <stub>}`. Must be JSON-serializable and deterministic.
  - `research(query)` → a **deterministic**, non-empty `list[Source]` (i.e. a `list[dict]`) derived from
    `query` — e.g. two canned sources whose text mentions the query. Same query → equal list. It must pass
    `json.dumps(...)` (JSON-native, SDK §5.5).
  - `attach` is accepted and ignored in the stub (real vision attachment is Stage B).
- **Not dry-run** (`current_context().dry_run` is false): raise `NotImplementedError` with a clear message,
  e.g. `"agents.llm: the OpenRouter adapter arrives in Stage B; run with dry_run=True"` (and likewise for
  `research`). Do not silently return a stub outside dry-run.

**Do not emit a cost event.** SDK §10's "records what it would have cost" belongs to the budget engine
(Stage C), which owns the cost/meter event schema. The Stage-A stubs return free stubs only; cost recording
is deferred (recorded in `docs/CHANGES.md`). Do not invent a `cost` event here.

## 2. `sdk/sfvf/__init__.py` — export `agents` and `Source`

Workflows import `from sfvf import ... agents` and may reference `Source`. Add `from . import agents` and
`from .agents import Source`, and add both `"agents"` and `"Source"` to `__all__`.

## Acceptance (the frozen contract `tests/sdk/test_agents.py`)

- `agents.llm` / `agents.research` raise (via `current_context`) when called with no active Context.
- In dry-run: `llm` returns a deterministic non-empty `str`; `llm(..., schema=...)` returns a `dict`;
  `research` returns a deterministic non-empty `list[Source]` whose items expose `str` `title`/`url`/`snippet`.
- Not in dry-run: `llm` and `research` raise `NotImplementedError`.

## Full local gate (all six must pass — run from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
.\.venv\Scripts\python.exe -m pytest
```

Do not weaken, skip, or edit any test to make the gate pass.
