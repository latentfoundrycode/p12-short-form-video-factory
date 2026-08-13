---
name: verify-project
description: how to run the project's linters and type checkers and interpret the results. Use after making code changes.
---

# Verify project

The shell is PowerShell. In each new terminal, run `.venv\Scripts\Activate.ps1` before any Python command. POSIX syntax will fail.

## Commands

```
python -m ruff check .
python -m ruff format --check .
python -m mypy
npm --prefix frontend run lint
npm --prefix frontend run typecheck
```

## Failures

- `ruff check` — lint violations in Python (bugs, unused code, enforced style).
- `ruff format --check` — files not matching the formatter; they would change under `ruff format`.
- `mypy` — type errors. Checks `app`, `sdk`, and `tools` only. Workflow code is deliberately excluded because each workflow's dependencies live in a separate virtual environment under `venvs/`.
- `npm --prefix frontend run lint` — ESLint reported problems in `frontend/`.
- `npm --prefix frontend run typecheck` — TypeScript compiler errors in `frontend/`.

## Fixing

- Python style: `python -m ruff check . --fix` then `python -m ruff format .`
- Frontend: `npm --prefix frontend run format` and `npm --prefix frontend run stylelint:fix`
- `mypy` and `typecheck` failures must be fixed by hand.

All five commands in Commands must pass before the work is considered done.
