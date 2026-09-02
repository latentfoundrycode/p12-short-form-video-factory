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

- `Source` — a small dataclass for a research result. The spec does not pin its shape, so use the minimal
  useful form: `@dataclass class Source: title: str; url: str; snippet: str`.
- Both functions read the ambient Context via `from ._runtime import current_context` to decide dry-run —
  they are **not** passed `ctx`. `current_context()` already raises if called outside a running workflow,
  which is the required "requires an active context" behaviour (do not catch it).
- **Dry-run** (`current_context().dry_run` is true):
  - `llm(...)` with `schema is None` → a **deterministic**, non-empty placeholder **string** (a pure
    function of its inputs — e.g. derived from `agent`/`model`/`prompt`; no RNG, clock, or `id()`). The
    same inputs must return the same string.
  - `llm(...)` with `schema` given → a **deterministic** placeholder **dict** (structured-output stub). A
    minimal shape is fine (real schema-shaped output is Stage B); it must be a `dict`.
  - `research(query)` → a **deterministic**, non-empty `list[Source]` derived from `query` (e.g. two
    canned sources whose text mentions the query). Same query → equal list.
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
