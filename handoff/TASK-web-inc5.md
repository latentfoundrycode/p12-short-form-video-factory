# TASK — web-sourcing inc5: source() high-level compose (checked selection)

## Context
`sdk/sfvf/media/web.py::source(...)` dry-run short-circuits to `want` stubs and raises
`NotImplementedError` on the real path. Build the real path (docs/DESIGN §3.2/§9.5): compose
`search` → `fetch` → `check_relevance` with early stop, each candidate's fetch+check inside its OWN
cached `ctx.step`. A frozen RED contract is committed: `tests/integration/test_media_web_source.py`
(do not edit it).

## Scope
- **Edit ONLY** `sdk/sfvf/media/web.py`, function `source` (the real, non-dry-run path).
- Do NOT change the dry-run branch or the `consider > _MAX_CONSIDER` guard (both already present).
- Do NOT change `search`/`fetch`/`check_relevance`. No test edits, no new files, no new deps.

## Required behaviour (real path, `not ctx.dry_run`)
```
n = max(0, want)                 # clamp: no negative-slice leakage
results: list[SourcedImage] = []
if n == 0:
    return results
candidates = search(query, sources=sources, limit=consider, licence=licence)
for c in candidates:             # search-provider RANK ORDER; `search` already bounds to `consider`
    with ctx.step(
        "web.source",
        # the cached verdict depends on the vision model too — include it so a _VISION_MODEL change
        # invalidates the entry (cache versioning keys on the workflow version, not the SDK revision)
        inputs={"url": c["url"], "subject": subject, "model": _VISION_MODEL},
        label=f"web.source:{c['url']}",
        paid=True,               # includes a paid VLM check -> PAID cache partition (resume doesn't repay)
    ) as step:
        if not step.cached:
            path = fetch(c)
            relevance = check_relevance(path, subject=subject, model=_VISION_MODEL)
            step.set({"path": path, "relevance": relevance})
        entry = step.value
    relevance = entry["relevance"]
    if relevance["score"] >= min_score:
        results.append(
            SourcedImage(path=entry["path"], candidate=c, relevance=relevance)
        )
        if len(results) >= n:
            break
return results
```

Key points (all pinned by the frozen contract):
- **Rank order + early stop:** iterate `candidates` in order; keep a candidate iff
  `relevance["score"] >= min_score`; stop once `len(results) == n`. So `source` may return FEWER than
  `want` when fewer qualify, and it does not fetch/check beyond the first `want` passes.
- **Fan-out bound:** `search(..., limit=consider, ...)` returns at most `consider` candidates, so at
  most `consider` fetch/check pairs run. (`consider > _MAX_CONSIDER` already raises above.)
- **Per-candidate cached `ctx.step`:** each candidate's fetch+check is wrapped in its own
  `ctx.step("web.source", inputs={"url", "subject"}, paid=True)`. On a cache hit (`step.cached`) reuse
  `step.value` (the step also restores the fetched image into `ctx.paths.video`), so a second identical
  `source(...)` run does NOT re-fetch or re-check. The value stored via `step.set(...)` is a plain
  JSON-serialisable dict (`{"path": str, "relevance": {...}}`).
- `want <= 0` → return `[]` with no search/fetch/check.
- The verdict read back from `step.value` is a plain dict; `relevance["score"]` etc. work (Relevance is
  a TypedDict = dict at runtime); `SourcedImage(path=..., candidate=c, relevance=relevance)` is fine.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_source.py tests/integration/test_media_web_surface.py -q`
  → **all pass** (source compose + per-candidate caching + end-to-end intake; surface unchanged).
- `python -m ruff format --check sdk/sfvf/media/web.py` and `python -m ruff check sdk/sfvf/media/web.py` → clean.
- `PYTHONPATH=sdk python -m mypy sdk/sfvf/media/web.py` → clean.
- `git diff --name-only` shows **only** `sdk/sfvf/media/web.py`.
