# TASK — web-image-sourcing inc6 FIX round 4: cap the mixed-source fan-out at `limit`

## Why this round
Cross-family Review B (round 4) found a **P1 cost-ceiling bypass**. In `sdk/sfvf/media/web.py::search()`
each tier is queried with the full `limit`, but the merged, de-duplicated result is **never capped**.
So `sources=("commons","web")` returns up to `2*limit`. Because `source()` calls `search(limit=consider)`
and runs one **paid** VLM `check_relevance` per returned candidate, `source(consider=50, sources=("commons","web"))`
fans out to ~100 paid checks — double the signed-off 50-candidate ceiling (`_MAX_CONSIDER`).

Reproduced: `search(..., sources=("commons","web"), limit=8)` returns 16 candidates.

A frozen RED contract is committed (HEAD): `tests/integration/test_media_web_web.py::test_mixed_source_search_caps_the_merged_result_at_limit`
(each tier returns `limit` distinct urls; the merged result must be exactly `limit`, commons-first order preserved).

## Change (exactly one file)
`sdk/sfvf/media/web.py::search()` — cap the de-duplicated result at `limit` before returning. The dedup
tail currently ends:
```python
    seen: set[str] = set()
    deduped: list[ImageCandidate] = []
    for c in out:
        if c["url"] not in seen:
            seen.add(c["url"])
            deduped.append(c)
    return deduped
```
Change the last line to cap the total at `limit` (preserving the existing commons-first first-seen order):
```python
    return deduped[:limit]
```
Rationale: `limit` is the total number of candidates the caller wants, not per-tier. A single-tier search
is already ≤ limit (the adapter bounds it), so `[:limit]` is a no-op there; only the mixed-tier union is
capped. This bounds `source()`'s paid VLM fan-out to `consider` (≤ `_MAX_CONSIDER` = 50).

Do NOT change per-tier dispatch (each tier is still queried with `limit` so either tier can supply the full
result if the other returns few), the dedup logic, the commons/web branches, the adapters, or `source()`
(its `consider > _MAX_CONSIDER` guard stays; the search cap makes its "search already bounds to consider"
comment true for mixed sources too).

## Scope
Only `sdk/sfvf/media/web.py`. No other file, no test, no adapter. No new dependencies.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_web.py -q` → all pass (the new cap
  test green; the existing mixed-dispatch/dedup test — limit=5, 3 results — still green).
- `PYTHONPATH=sdk python -m pytest tests/integration/test_media_web_commons.py tests/integration/test_media_web_surface.py tests/integration/test_media_web_fetch.py -q` → still pass.
- `ruff check sdk tests` and `ruff format --check sdk tests` clean.

## Then (supervisor, on resume)
Inspect the diff, run Review A (diff-reviewer + secret-sentinel + security-auditor), commit + push, run
cross-family Review B round 5 (scope: confirm the cap enforces the ceiling and did not change single-tier
behaviour or the budget/billing-boundary/redaction fixes), poll the CI gate, then `gh pr merge 147 --squash`.
