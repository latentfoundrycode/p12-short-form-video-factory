# TASK G-7a — learning optimiser core (messages + parse) (§5.11)

## Goal (one sentence)
Add `app/learning/optimizer.py` with the pure, UNPAID core of the SkillOpt-derived optimiser: build
chat messages from a `LearningInput`, and parse a chat completion back into bounded `ProposedEdit`s.
The paid OpenRouter call is injected as `complete` (always a stub in tests) — no network, no spend.

## Governing spec (verbatim — Architecture §5.11)
> gather every `video.json` containing quality answers since the last learning run, load that
> workflow's criteria files together with its current rules and skills, and run the SkillOpt-derived
> optimiser to propose bounded edits.
>
> **Only files inside `workflows/<id>/rules/` and `workflows/<id>/skills/` may be modified.** Any
> proposal touching a path outside that is rejected outright.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_learning_optimizer.py`.

## What to implement — `app/learning/optimizer.py` (new)
Reuse the existing shapes from `app/learning/engine.py`: `LearningInput`, `ProposedEdit`, and the
`OptimizeFn` type alias. Import them; do not redefine them.

Define:
- `class OptimizerError(Exception)` — raised on any unparseable / out-of-bounds optimiser response.
- `type CompleteFn = Callable[[list[dict[str, str]]], str]` — an injected chat-completion callable:
  it takes the messages and returns the assistant message content (expected to be JSON). This is the
  seam the paid OpenRouter call plugs into later; here it is always a stub.

Functions:
- `build_optimizer_messages(learning_input: LearningInput) -> list[dict[str, str]]`
  - Returns at least two messages, each a plain `{"role": str, "content": str}` dict (exactly those
    two keys). The first message's role is `"system"` (the optimiser's standing instructions); at
    least one `"user"` message carries the workflow data.
  - The combined content MUST include: the workflow id; each editable file's name **and body** from
    `learning_input.rules` and `learning_input.skills`; the read-only `criteria` (as context the
    optimiser may consult but must not edit); and the quality evidence in `learning_input.labels`
    (answer values, rankings, accept/reject) so the model can see what to improve.
  - The system message must instruct the model to (a) propose edits ONLY to files under `rules/` or
    `skills/`, and (b) reply with a JSON object `{"edits": [{"path": "...", "content": "..."}, ...]}`
    where `path` is the workflow-relative POSIX path (e.g. `rules/tone.md`) and `content` is the FULL
    new file body. Wording is yours; the tests assert the data is present, not the exact prose.
- `parse_optimizer_response(text: str) -> list[ProposedEdit]`
  - Strip a leading/trailing markdown code fence if present (```json … ``` or ``` … ```), then parse
    JSON. Accept a top-level object with an `"edits"` array. (A bare top-level list may also be
    accepted, but is not required by the contract.)
  - Each entry must be an object with string `path` and string `content` → one `ProposedEdit`.
  - Validate every `path` with the SAME rule as `engine._validate_edits` (mirror it): reject if the
    raw string contains `\` or `:`, or as a `PurePosixPath` it is absolute, contains `..`, has fewer
    than 2 parts, or `parts[0]` is not in `{"rules", "skills"}`. Any violation → raise
    `OptimizerError`. An empty `edits` array → return `[]` (a no-op run).
  - Malformed JSON, wrong shape, or a non-string path/content → raise `OptimizerError`.
- `make_optimizer(complete: CompleteFn) -> OptimizeFn`
  - Returns `optimize(learning_input)` that calls `complete(build_optimizer_messages(learning_input))`
    exactly once and returns `parse_optimizer_response(...)` of the result.

## Constraints / do-nots
- Touch ONLY `app/learning/optimizer.py` (new). Do NOT edit the test, `engine.py`, or anything else.
- No network, no HTTP client, no secrets, no budget in THIS file — the paid call is injected via
  `complete` and wired in a later increment. Stdlib only (`json`, `re`, `pathlib`, `collections.abc`,
  `dataclasses`/`typing` as needed).
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/optimizer.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_optimizer.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
