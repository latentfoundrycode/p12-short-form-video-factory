# TASK-SSN-C2-r3 — Fix two Review-B blockers in prepare()/allowlist

The cross-family merge-gate reviewer (Review B) REJECTed Stage C with two blocking defects plus two
related correctness gaps, all in `workflows/sensational-science-news/main.py`. This task fixes them.
Frozen tests are already committed and RED; make them green WITHOUT editing any test.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Do NOT modify any test, SDK file, other workflow, or dependencies. Stdlib imports only. Stay in this
checkout (`Workspace/`).

## Frozen tests to make green (read them first)

`tests/integration/test_ssn_prepare.py`:
- `test_allowlist_filter_rejects_percent_encoded_traversal`
- `test_prepare_reselects_per_request_not_from_cache`
- `test_prepare_cross_run_dedup_is_case_insensitive`
- `test_prepare_raises_when_pool_exhausted_by_dedup`

All the other existing tests (prepare/script/gate/registry/dry-run) must STAY green.

## Fix 1 — allowlist path filter: percent-decode before normalizing (BLOCKING)

`_url_on_allowlist` (around main.py:60-73) runs `posixpath.normpath` on the RAW path. Literal `../` is
removed, but percent-encoded `%2e%2e` / `%2f` are left intact and slip past the `/`-bounded prefix
check, so `https://www.bbc.com/news/science_and_environment/%2e%2e/%2e%2e/entertainment/x` is wrongly
KEPT (it resolves to `/entertainment/x`, outside the `/news/science_and_environment` prefix).

Fix: percent-DECODE the path before normalizing (RFC 3986 order: decode, then remove dot-segments).
- Add `unquote` to the existing import: `from urllib.parse import unquote, urlparse`.
- Change the path handling to decode first:
  ```python
  raw_path = unquote(parsed.path or "")
  path = posixpath.normpath(raw_path or "/")
  ```
  Keep the existing `if path == ".": path = "/"` guard and the existing boundary check
  (`path == path_prefix or path.startswith(path_prefix + "/")`).

## Fix 2 — choose-subjects caching defeats cross-run dedup + drops sources (BLOCKING)

`prepare()` (main.py:355-429) wraps everything in `ctx.step("choose-subjects", inputs={"count": n})`.
The step cache root is shared across runs (per workflow + mode), so a SECOND real request with the
same video count HITS the cache and replays the first request's subjects — cross-run dedup and fresh
research never run again — and because `sources_map` is only assigned inside `if not step.cached`, a
hit returns `"sources": {}`.

Fix, following the SDK's caching rules (resolve library state outside the step; declare what makes the
result vary in `inputs`; the just-selected result must be fully captured in the cached value):

1. Add `from datetime import date` at the top.
2. Read `used-subjects` OUTSIDE (before) the `ctx.step` block, and derive BOTH:
   - `stored_used: list[str]` (original case, for display + the append), and
   - `used_fold: set[str]` = `{u.casefold() for u in stored_used}` (for case-insensitive dedup).
   (Move the current lines 374-378 out above the `with ctx.step`; drop the old `used = set(stored_used)`.)
3. Key the step per request so each request re-selects but a resume of the same run stays stable:
   ```python
   with ctx.step(
       "choose-subjects",
       inputs={"count": n, "run_id": ctx.run_id, "as_of": date.today().isoformat()},
   ) as step:
   ```
   (`ctx.run_id` is unique per request and stable across a resume of that run; `as_of` keeps it
   recency-fresh.)
4. Inside the step body, use `stored_used` for the human-readable `used_text` (not the casefold set),
   and pass `used_fold` to `_finalize_subject_list` (see Fix 3).
5. POOL EXHAUSTED: after computing `chosen`, if `len(chosen) < n`, raise
   `RuntimeError(f"only {len(chosen)} fresh on-allowlist subjects available for {n} videos; ...")`.
   This prevents `run()` from later `IndexError`-ing on `ctx.shared["subjects"][video_index - 1]`.
   (The existing empty-allowlist-pool RuntimeError stays as-is, including its dry-run raw fallback.)
6. Cache BOTH subjects and sources, and read them back from the step value so a cache hit returns
   sources too:
   ```python
   sources_map = _build_sources_map(chosen, pool)
   ...            # (keep the used-subjects append/cap block)
   step.set({"subjects": chosen, "sources": sources_map})
   result = step.value
   return {"subjects": result["subjects"], "sources": result["sources"]}
   ```
   (Move the `return` to use `step.value` outside the `if not step.cached`, so a hit path also returns
   the cached subjects + sources. Remove the module-level `sources_map` pre-initialization if it is no
   longer used.)

The `used-subjects` append (the `merged` / `_USED_SUBJECTS_CAP` block) stays; it appends the
original-case `chosen` to `stored_used`. Keep it inside `if not step.cached`.

## Fix 3 — cross-run dedup is case-insensitive

`_finalize_subject_list` (main.py:143) currently takes `used: set[str]` and compares `canonical in
used` and `title in used` (exact case). Change it to treat `used` as a set of ALREADY-CASEFOLDED
strings and compare with casefold:
- `if canonical.casefold() in used: continue`
- backfill loop: `if title.casefold() in used: continue` (keep the existing `if not title` guard).
Update the param name/docstring to make clear `used` is a casefolded set. Its caller now passes
`used_fold` (Fix 2). The within-run duplicate check via `seen_fold` already uses casefold — leave it.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_prepare.py -q` — all pass (the 4
  new tests plus the originals).
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_script.py tests/integration/test_ssn_gate.py tests/registry/test_ssn_workflow.py tests/integration/test_ssn_workflow_dry_run.py -q` — still green (the dry-run pipeline still renders; note each test run has a unique run_id so it always selects fresh).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no NEW errors from `main.py` (pre-existing PIL error unrelated).

Print the updated `_url_on_allowlist`, the new `prepare()` step block, and `_finalize_subject_list`,
and one line each on: how encoded traversal is now rejected, and why a second request no longer reuses
the first request's subjects.
