# TASK — close the learning loop: a workflow's rules/skills must reach generation (§5.11)

## Goal (one sentence)
Load each workflow's `rules/*.md` + `skills/*.md` into the run context and have `agents.llm` /
`agents.research` inject their content into every LLM prompt, so accepted learning edits actually
steer generation (today `ctx.instructions` is `[]` and nothing consumes it, so rules are ignored).

## Frozen contract (already committed — do NOT edit)
- `tests/integration/test_agents_instructions.py` (SDK injection)
- `tests/core/test_supervisor_instructions.py` (supervisor loading)

## What to implement — TWO files

### 1) `app/core/supervisor.py` — load the instruction paths
Add a module-level helper:
```python
def instruction_paths(workflow_dir: Path) -> list[Path]:
    """The frozen instruction files (rules then skills) that apply to a run, sorted within each and
    returned as absolute paths so the child subprocess can read them."""
    result: list[Path] = []
    for sub in ("rules", "skills"):
        directory = workflow_dir / sub
        if directory.is_dir():
            result.extend(sorted(p.resolve() for p in directory.glob("*.md") if p.is_file()))
    return result
```
Then wire it into `_make_context`: replace `instructions=[]` (currently at ~line 275) with
`instructions=instruction_paths(wiring.workflow_dir)`. (`wiring.workflow_dir` is the same value already
passed to `ContextPaths(workflow=wiring.workflow_dir)`.) Nothing else in `_make_context` changes.

### 2) `sdk/sfvf/agents.py` — inject the instruction content into every LLM call
The single choke point for both `llm()` and `research()` is `_post_chat_completion(ctx, body)`.
Before posting, prepend the instructions as ONE leading `system` message:
- Add a helper:
  ```python
  def _instruction_text(ctx: Context) -> str:
      parts: list[str] = []
      for path in ctx.instructions:
          try:
              text = Path(path).read_text(encoding="utf-8").strip()
          except OSError:
              continue          # a missing/unreadable instruction file must never break a call
          if text:
              parts.append(text)
      return "\n\n".join(parts)
  ```
- In `_post_chat_completion`, at the very top (before the reservation / client is fine — anywhere
  before the POST), compute `instructions = _instruction_text(ctx)` and, if non-empty,
  `body["messages"] = [{"role": "system", "content": instructions}, *body["messages"]]`.
  When `ctx.instructions` is empty the body is unchanged (backward-compatible — existing agents tests
  send `instructions=[]` and must still see exactly their original messages).

Notes:
- `Context` and `Path` are already imported in `agents.py` (Context under `TYPE_CHECKING`); import
  what you need without breaking the existing import style.
- Do NOT strip a workflow's frontmatter or otherwise transform the rule text — inject it verbatim
  (the contract only asserts the content appears; keep it simple).
- The content is data, but it is the workflow's own rule text (not a secret) — the existing
  secret-redaction/dry-run behaviour is unchanged; dry-run still stubs and makes no call.

## Constraints / do-nots
- Touch ONLY `app/core/supervisor.py` and `sdk/sfvf/agents.py`. Do NOT edit the tests or anything else.
- Keep `ruff check .`, `ruff format --check .`, and `mypy` (the CI command `python -m mypy`) clean;
  ≤100 cols.

## Scope
- `app/core/supervisor.py`
- `sdk/sfvf/agents.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe` — a REAL venv with the worktree's sdk)
- `-m pytest tests/integration/test_agents_instructions.py tests/core/test_supervisor_instructions.py -q` → all pass.
- `-m pytest -q` (full) → green (existing agents/supervisor tests must still pass; the injection is a
  no-op when instructions is empty).
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy` → clean.
