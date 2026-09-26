# TASK-SSN-C2-r2 — Harden prepare(): ground subjects to sources + bound persistence

Your C2 implementation of `workflows/sensational-science-news/main.py` was reviewed. Review A
approved it and all original tests pass. A security review found two BLOCKING issues plus some
advisories. This task fixes them. The frozen tests have been updated to encode the corrected
contract; make them green WITHOUT editing any test.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Do NOT modify any test, SDK file, other workflow, `workflow.toml`, `requirements.txt`, or
dependencies. Stay inside this checkout (`Workspace/`).

## The two BLOCKING fixes

### 1. Ground every chosen subject to a vetted on-allowlist pool source (membership validation)

The picker LLM is fed UNTRUSTED source titles/snippets, so a prompt injection in that text could
make it emit an arbitrary attacker-controlled string as a "subject". Today `_finalize_subject_list`
accepts the LLM's `picked` strings verbatim, so such a string would be returned AND written into the
persistent `used-subjects` asset, where it replays into every future picker prompt.

Fix: a chosen subject is only valid if it matches (case-insensitively) the `title` of a source in
the on-allowlist `pool`. In `_finalize_subject_list`, when iterating the LLM's `picked` list, DROP
any entry whose casefold does not equal the casefold of some pool source title. Keep the existing
dedup-vs-`used` and distinct-preserving-order logic and the N cap. The backfill step (pull from pool
source titles when short) already yields grounded titles — keep it. When you DO accept a picked
entry, prefer emitting the pool's exact title string for that match (so persisted/returned subjects
are the canonical source title, not a reformatted variant). Net effect: every returned/persisted
subject is a real on-allowlist source title. (This also means `_build_sources_map` will always match
a subject to its source by title.)

Note the design intent: the SUBJECT identifies WHICH real story to cover (grounded, vetted); the
sensational/captivating TREATMENT happens later in the script step (a separate increment). Do not
try to make the subject itself a sensational framing.

### 2. Bound the persistent `used-subjects` asset (most-recent window)

Today the write is `sorted(used | set(chosen))` — it grows by up to N entries every run, forever,
and the whole list is read back and inlined into the picker prompt each run (unbounded prompt size,
token cost, and exclusion set).

Fix: store `used-subjects` as an ORDER-PRESERVING list (oldest first, newest last), and cap it to
the most-recent `_USED_SUBJECTS_CAP` entries, dropping the oldest beyond the cap. Add a module
constant `_USED_SUBJECTS_CAP = 500`. On write: take the existing stored list (in stored order),
append the newly `chosen` subjects, de-duplicate preserving order (first occurrence wins is fine,
but the just-chosen subjects MUST be retained — if a chosen subject already existed, its presence is
enough), then keep only the last `_USED_SUBJECTS_CAP` entries. Read side stays a membership set for
exclusion (`used = set(stored_list)`). The just-chosen subjects must always survive the cap (they
are newest).

Because the stored value is now an ordered list, do NOT re-`sorted()` it on write (that would
destroy recency). Reading with `set(...)` for exclusion is unchanged and order-agnostic.

## Advisory fold-ins (do these too — they are cheap and correct)

3. `_url_on_allowlist`: compare `urlparse(url).hostname` (already lower-cased, and correctly
   excludes any userinfo/port) instead of `parsed.netloc`. This keeps the fail-closed behaviour for
   lookalike/subdomain hosts (`evil.example.com` still normalises to itself, not to `nature.com`)
   while no longer wrongly rejecting a legitimate allowlisted URL that carries an explicit port.
   `hostname` can be `None` (e.g. a scheme-less or malformed URL) — treat `None` as no match.
4. `_url_on_allowlist` path check: normalise the path before the boundary comparison so a traversal
   like `/science/../markets` cannot slip under a `/science` prefix. Use
   `posixpath.normpath(parsed.path or "/")` (import `posixpath`), then apply the existing
   `path == prefix or path.startswith(prefix + "/")` boundary check. A path of `""` normalises to
   `"."` — guard so an empty path still behaves as `/` (root), i.e. only matches an empty prefix.
5. Cap the research pool that is inlined into the picker prompt: introduce
   `_POOL_PROMPT_LIMIT = 40` (max sources) and truncate each title/snippet to a sane length
   (e.g. 200 chars) when building `pool_text`. This bounds prompt tokens/cost against an oversized
   or attacker-inflated result set. The FULL pool may still be used for membership validation and
   backfill; only the text handed to the LLM is capped.
6. Read the library with `if ctx.library is not None` (matching the write guard), not the truthiness
   check `if ctx.library`.

## Done when

Run from `Workspace/` with the repo venv:

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_prepare.py -q` — all 6 pass,
  including `test_prepare_drops_non_pool_injected_subject` and
  `test_prepare_caps_used_subjects_growth`.
- `./.venv/Scripts/python.exe -m pytest tests/registry/test_ssn_workflow.py tests/integration/test_ssn_workflow_dry_run.py -q` — still green (the C1 dry-run pipeline still produces a finished video and N subjects; grounding + backfill still yields N in dry-run because the two canned dry-run sources have distinct titles).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` — clean.
- `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no NEW errors from `main.py` (a pre-existing PIL error in
  `sdk/sfvf/media/web.py` is unrelated; leave it).

Print the updated `_finalize_subject_list`, `_url_on_allowlist`, and the `used-subjects` write block,
and one line each on: how membership grounding drops an injected subject, and how the cap keeps the
just-chosen subjects while evicting the oldest.
