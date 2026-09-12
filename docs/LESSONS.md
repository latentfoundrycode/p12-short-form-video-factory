# Lessons

Running record of misconceptions or mistakes the build loop made and what it learned. One entry
each: what was wrong, how it surfaced, the correction. Generalizable entries are candidates for
promotion into the cross-project pitfalls catalogue.

- **A secret-leak test stub read the injected secret from `os.environ`, not `ctx.secret()` (E-3).**
  What was wrong: the supervisor-authored contract stub `tests/stubs/leaks_self_review_secret` read
  `os.environ.get("OPENROUTER_API_KEY", "")` and declared no `[[requires_keys]]`. Secrets are
  injected into a workflow only via the `ctx.secret(NAME)` path with the key declared in
  `[[requires_keys]]` (the mechanism that also registers the value into the supervisor's redaction
  set), so the stub's `leaked` would have been empty — the redaction test would have been vacuous
  (nothing to redact), silently passing without exercising the write-path redaction it claimed to.
  How it surfaced: the builder corrected the stub to match the existing `leaks_cost_secret` template
  (`ctx.secret(...)` + `[[requires_keys]]`), and the deterministic `scope-check.py` flagged the
  out-of-scope stub edit so it was reviewed rather than passing silently — both gates working.
  Correction: any test that exercises secret injection/redaction must read the value via
  `ctx.secret(NAME)` and declare the key under `[[requires_keys]]`, mirroring `leaks_cost_secret`;
  never `os.environ`. The supervisor's own frozen contracts get the same scrutiny as the builder's
  code — a wrong stub makes a real check vacuous.
- **The Vite frontend build wipes `app/web/.gitkeep` (E-4b).** What was wrong: running
  `npm --prefix frontend run build` (Vite with `emptyOutDir` into `app/web/`) deletes the tracked
  `app/web/.gitkeep` placeholder — the only tracked file keeping `app/web/` present in the repo (the
  built `index.html`/`assets/` are gitignored). If committed, a fresh checkout would lack `app/web/`
  and the backend's static mount could break. How it surfaced: secret-sentinel + diff-reviewer both
  flagged the `D app/web/.gitkeep` in the changeset (the scope-check ran BEFORE the build and so
  missed it — the deletion is a build side effect, not a builder edit). Correction: after running the
  frontend build in a worktree, `git checkout HEAD -- app/web/.gitkeep` before committing; never
  commit its deletion. A durable fix (deferred) is a Vite config that preserves the placeholder.
