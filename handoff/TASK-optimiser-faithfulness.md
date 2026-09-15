# TASK — optimiser faithfulness: encode the user's stated preferences, don't invert them

## Goal (one sentence)
Reword the optimiser's system prompt so it treats the user's quality answers as authoritative
directives and encodes their stated preferences faithfully — never overriding or inverting them.

## Why
The current prompt says "Improve a workflow's instruction files **from quality evidence**", so the
model treats answers as evidence to reason over and applies its own taste: a user's explicit "the
video must state the date" came back as a rule to NOT state the date. The optimiser must instead
faithfully translate what the user asked for into rules.

## Frozen contract (already committed — do NOT edit)
`tests/core/test_learning_optimizer.py` — including the new
`test_system_prompt_encodes_user_preferences_faithfully` (the system prompt lowercased must contain
"faithful" and one of "invert"/"override"). All existing optimiser tests must stay green.

## What to change — `app/learning/optimizer.py` only
Replace the `_SYSTEM_PROMPT` string constant with the following text (keep it as a string constant;
you may keep the existing multi-line `(... "" ...)` concatenation style, and keep the exact JSON-shape
and rules/skills-only wording — only the framing changes):

> You are a SkillOpt-derived optimiser. You revise a workflow's instruction files so future videos
> better match the user's judgement.
> The quality answers are the user's own words about what they wanted — treat them as AUTHORITATIVE
> directives, not as evidence to second-guess. Encode the user's stated preferences faithfully: if a
> user says a video must do something (or must not), write a rule that says exactly that. Do NOT
> override, soften, or invert a stated preference because you disagree with it or think it is bad
> practice — your job is to capture what the user wants, not to impose your own taste.
> Propose edits ONLY to files under rules/ or skills/. Do not edit criteria or any other path.
> Reply with a JSON object of this exact shape: {"edits": [{"path": "...", "content": "..."}, ...]}.
> path is the workflow-relative POSIX path (e.g. rules/tone.md) and content is the FULL new file body.
> Return {"edits": []} if nothing should change.

Keep the JSON braces correctly escaped in the Python string (the `{"edits": [...]}` shape must appear
literally in the prompt, as it does today). Do not change `build_optimizer_messages`,
`parse_optimizer_response`, or anything else — only the `_SYSTEM_PROMPT` text.

## Constraints / do-nots
- Touch ONLY `app/learning/optimizer.py`. Do NOT edit any test or other file.
- The prompt must still contain the exact JSON-shape instruction and the "rules/ or skills/ only"
  restriction (existing tests + the parse guard depend on the shape).
- Keep `ruff check .`, `ruff format --check .`, `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/learning/optimizer.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_learning_optimizer.py -q` → all pass (incl. the new faithfulness test).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
