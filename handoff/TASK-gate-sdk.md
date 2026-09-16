# TASK — H-1: `ctx.gate()` interactive approval gate (SDK)

## Goal (one sentence)
Add the workflow-facing gate primitive: `ctx.gate(...)` emits a `gate` event and blocks on a response
file until the user answers (returning the decision, raising `GateRejected` on reject), with a
scheduled-bypass path and a resume-idempotent token; plus `ctx.gate_attempts(...)`.

## Spec (Architecture §3.5, Workflow Authoring Guide §4.6) — authoritative
`ctx.gate(family, *, prompt, payload=None, options=None, items=None, select=None, on_bypass=None)
-> dict`. Three shapes:
- **Approval** (`prompt`, optional `payload`) → `{"choice": "approve" | "reject"}`.
- **Choice** (`options=[...]`) → `{"choice": "<one of options>"}`.
- **Selection** (`items=[...]`, `select="subset"`) → `{"choice", "keep":[ids], "redo":[ids], "note"}`.

Rules: `{"choice":"reject"}` raises `GateRejected`. `on_bypass` is MANDATORY for any shape that can
return more than plain approval (choice/selection); a plain-approval gate may omit it. Gate durations
are recorded but excluded from step timing (not this increment's concern).

## Frozen contract (already committed — do NOT edit)
`tests/sdk/test_gate.py`. All existing tests must stay green.

## What to change

### 1. New module `sdk/sfvf/gate.py`
Define the exception and the gate logic. Public: `GateRejected(Exception)`.

**Token & response-file protocol.**
- Each `ctx.gate()` call gets a deterministic token `f"{family}-{occurrence}"`, where `occurrence`
  is the number of PRIOR `ctx.gate()` calls with the same `family` on this Context (0-based). Track
  the per-family counter on the Context (e.g. `ctx._gate_counts: dict[str, int]`, init in
  `Context.__init__`). Determinism across a resume comes from the workflow re-executing the same
  `gate()` calls in the same order.
- The response file is `ctx.video_dir / "gates" / f"{token}.json"`, a JSON object holding the
  decision.

**`run_gate(ctx, family, *, prompt, payload, options, items, select, on_bypass) -> dict`** (called by
`Context.gate`):
1. **Validate the shape** (raise `ValueError` on misuse): `options` and `items` are mutually
   exclusive; `select` may only be `"subset"` and only with `items`; `items` requires `select=
   "subset"`; each item is a dict with a string `"id"`. Determine `shape`:
   `"choice"` if `options`, `"selection"` if `items`, else `"approval"`.
2. Compute `token`; `response_path = ctx.video_dir / "gates" / f"{token}.json"`.
3. **Already answered (resume / pre-written):** if `response_path` is a file, read+parse it and
   return via the validate-and-return path below (this makes a resumed run re-use the prior
   decision, and lets a test pre-write one). Do NOT emit a new event in this case.
4. **Bypass:** else if `ctx.gates_auto` is true, synthesize the decision from `on_bypass`
   (`_bypass_decision(shape, items, on_bypass)` — see below), WRITE it to `response_path` (creating
   `gates/`), and return it (validate-and-return). For a shape that can return more than approval,
   a missing/None `on_bypass` is a `ValueError` (authoring error — the chassis never invents a
   default). Emitting the event here is optional; the test does not require it.
5. **Interactive:** else emit the gate event (see shape below), then poll: loop
   `while not response_path.is_file():` — if `(ctx.video_dir / ".stop").exists()` raise
   `GateRejected("run stopped at gate")` (or a dedicated exception subclass) so a graceful stop while
   parked at a gate does not hang; else `time.sleep(_GATE_POLL_SECONDS)`. Use
   `_GATE_POLL_SECONDS = 0.05`. When the file appears, read+parse and validate-and-return.

**Validate-and-return** (`_finish(decision) -> dict`): `decision` must be a dict with a string
`"choice"`. If `choice == "reject"` → raise `GateRejected` (carry the `note` if present in the
message). For selection, coerce/return `keep`/`redo` as lists of strings and `note` as a string
(default `""`/`[]` when absent). Return the decision dict (the tests compare specific keys, not the
exact dict identity, so returning the parsed dict — plus normalized keep/redo/note for selection —
is fine).

**Gate event shape** (emit via `ctx.emit(...)` so it lands on stdout / `events.jsonl`):
```python
{"t": "gate", "family": family, "token": token, "shape": shape, "prompt": prompt}
```
plus, when present: `"payload"`, `"options"`, `"items"`, `"on_bypass"`. Do NOT inline artifact bytes
— `items[].artifact` stays a path string.

**`_bypass_decision(shape, items, on_bypass)`:**
- approval: `on_bypass` may be `None` → `{"choice": "approve"}`; if `on_bypass == "reject"` →
  `{"choice": "reject"}`.
- choice: `on_bypass` must be one of `options` → `{"choice": on_bypass}` (missing → ValueError).
- selection: `on_bypass` required (missing → ValueError). `"approve-all"` →
  `{"choice":"approve","keep":[every item id],"redo":[],"note":""}`; `"reject"` →
  `{"choice":"reject"}`.

**`gate_attempts(ctx, family, *, item=None) -> int`** (called by `Context.gate_attempts`): read every
`ctx.video_dir / "gates" / f"{family}-*.json"` response file; when `item` is given, return the count
of those decisions whose `redo` list contains `item`; when `item is None`, return the count of those
whose `choice` is `reject` OR whose `redo` is non-empty (a "this needs another attempt" signal).
Missing `gates/` dir → 0. Ignore unreadable/malformed files.

### 2. `sdk/sfvf/context.py`
- Add `gates_auto: bool = Field(default=False, description="...")` to `ContextFile` (a scheduled
  run with gate-bypass sets this; default False for interactive runs).
- In `Context.__init__`: `self.gates_auto = file.gates_auto` and `self._gate_counts: dict[str,int]
  = {}`.
- Add methods delegating to `sfvf.gate`:
  ```python
  def gate(self, family, *, prompt, payload=None, options=None, items=None,
           select=None, on_bypass=None) -> dict[str, Any]:
      return run_gate(self, family, prompt=prompt, payload=payload, options=options,
                      items=items, select=select, on_bypass=on_bypass)

  def gate_attempts(self, family, *, item=None) -> int:
      return gate_attempts(self, family, item=item)
  ```
  (Increment the per-family occurrence counter inside `run_gate` when computing the token, so it
  advances once per call.)

## Constraints / do-nots
- Touch ONLY `sdk/sfvf/gate.py` (new) and `sdk/sfvf/context.py`. Do NOT edit any test or other file.
- Do NOT import from `app.*` (the SDK must not depend on the backend). The `.stop` sentinel name is
  the wire protocol — define `_STOP_SENTINEL = ".stop"` locally with a comment.
- No new third-party dependency.
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Review B follow-up (SECOND delegation — four fixes to `sdk/sfvf/gate.py`)
Cross-family review found four real edges. Apply all four; new frozen tests pin #2 and #4.

1. **Validate `on_bypass` up-front, always (not only under `gates_auto`).** In `run_gate`, right after
   shape validation and BEFORE the resume/bypass/interactive branches, for `shape in ("choice",
   "selection")` require `on_bypass` and check its legality — choice: `on_bypass` must be one of
   `options`; selection: `on_bypass` must be `"approve-all"` or `"reject"`. Raise `ValueError` on
   missing/illegal. (Approval: `on_bypass` optional, must be None/`"approve"`/`"reject"` if given.)
   This catches an authoring error that would otherwise only surface when the gate is scheduled, and
   makes an interactive richer-shape gate with no `on_bypass` fail fast instead of blocking forever.
   Then simplify `_bypass_decision` to trust the already-validated `on_bypass`.

2. **`gate_attempts`: match the family EXACTLY.** `glob(f"{family}-*.json")` wrongly matches a longer
   family (`gate_attempts("approve")` counts `approve-sheets-0.json`). Instead iterate `gates_dir.glob
   ("*.json")`, and for each file parse the stem as `"<family>-<occurrence>"` by `rsplit("-", 1)`;
   require the right part to be all digits and the LEFT part to equal `family` exactly; skip
   non-matching. (Also avoids glob-metacharacter surprises in a family name.)

3. **Tolerate torn reads + write bypass atomically.** A response file can momentarily exist empty or
   half-written while the backend writes it. (a) In the interactive poll, wrap the
   `json.loads(read_text(...))` for the appeared file in `try/except (OSError, ValueError,
   json.JSONDecodeError)`: on failure, treat it as "not ready yet" — keep polling (do not crash). (b)
   The bypass write must be atomic: write to a temp file in the same `gates/` dir then
   `os.replace(tmp, response_path)`, so no reader ever sees a partial bypass file. (The resume
   short-circuit read at the top may stay a plain read — if it is torn it is a genuinely corrupt file,
   not a live-write race; but wrapping it in the same tolerant try and falling through to
   poll/bypass is acceptable and preferred.)

4. **Make the per-family occurrence counter increment atomic.** Two concurrent same-family `gate()`
   calls can both read the same `occurrence` (a lost update → same token → same response file). Guard
   the read-increment of `ctx._gate_counts[family]` with a module-level `threading.Lock`. (This
   prevents token collision; note in a comment that gate ORDER across a resume still assumes gates are
   called sequentially from the workflow's main flow, not concurrently from `ctx.map` workers — that
   ordering guarantee is a documented limitation, not fixed here.)

Keep everything else. Touch ONLY `sdk/sfvf/gate.py`. Keep lint/format/mypy clean.

## Scope
- `sdk/sfvf/gate.py`
- `sdk/sfvf/context.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_gate.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
