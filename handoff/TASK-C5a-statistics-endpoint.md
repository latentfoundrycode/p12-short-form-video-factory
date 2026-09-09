# TASK C-5a — statistics spend-aggregation endpoint (PRD §8.6, §7.1)

## Goal (one sentence)
Fill three skeleton bodies so the Statistics tab's backend can report actual spend over time, per
meter, grouped by kind (fiat combined into one line; credit meters never combined).

## Frozen contract (already committed — do NOT edit any test)
- `tests/core/test_meters.py` — `meter_info` classification.
- `tests/core/test_statistics.py` — `aggregate_statistics` semantics (the money logic).
- `tests/api/test_statistics_api.py` — `GET /api/statistics` shape + `months` clamping.
The names/signatures of `MeterInfo`, `METERS`, `meter_info`, `Bucket`, `Series`,
`aggregate_statistics`, and the route are FROZEN. Do not change them or the response models.

## What to implement (only the three `raise NotImplementedError` bodies)

### 1. `app/core/meters.py` — `meter_info(meter, registry=METERS)`
Return `registry[meter]` when present; otherwise a standalone-credit fallback
`MeterInfo(kind="credit", provider=meter, unit="credits")`. An unknown meter must NEVER be classed
as fiat (that would let it be summed into the fiat total).

### 2. `app/core/statistics.py` — `aggregate_statistics(runs_dir, *, months, now, registry=METERS)`
Pure, read-only, tolerant. Steps:
- **Window**: the `months` calendar months ending with `now`'s month, inclusive. Build the ordered
  list of `"YYYY-MM"` month keys ascending (e.g. `now`=2026-09, months=6 →
  `["2026-04",...,"2026-09"]`). Assume `months >= 1` (the route clamps).
- **Walk runs**: for each `runs_dir/<workflow>/<run>/request.json`, read the `RequestRecord`
  (`app.core.records.read_request`; skip a run dir that can't be read — wrap in try/except like
  `app/core/estimate.py::_try_read_request`). Skip the run when `record.dry_run` is true. Determine
  the run's month from `record.started_utc` (parse the leading `YYYY-MM`; a value that doesn't parse
  → skip the run). Skip runs whose month is not in the window. **Do NOT filter on status** — a
  stopped/failed run still spent real money and must be counted (this differs from estimation).
- **Sum actual spend**: for each video dir in the run with a `video.json`
  (`app.core.records.read_video`; skip unreadable), take `video.cost["actual"]` (a `dict[str,float]`;
  if `cost` is not a dict or has no `actual` dict, skip). For each `meter, raw` in it, coerce like
  `estimate.py::_run_uncached`: reject `bool`; require `int|float`; `float(raw)` inside
  `try/except (OverflowError, ValueError)`; skip if `not math.isfinite(amount)` or `amount < 0`.
  Accumulate into a `{(series_id, month): amount}` structure, where the series id is `"fiat"` for a
  meter whose `meter_info(meter, registry).kind == "fiat"`, else the meter id itself. Guard the
  running sum for finiteness (skip a term that would make the total non-finite), matching estimate.py.
- **Build series**:
  - The **fiat** series (id `"fiat"`, kind `"fiat"`, label `"Fiat currency"`) exists iff at least one
    fiat meter contributed. `providers` = sorted unique `meter_info(m).provider` of the fiat meters
    that appeared. `unit` = the unit of those fiat meters (they share one; take any — e.g. the first
    fiat meter's unit by sorted meter id). Its `buckets` = one `Bucket(month, amount)` per window
    month (ascending, zero where nothing accrued). `total` = sum of bucket amounts.
  - Each **non-fiat** meter that appeared gets its own series: id = meter id, kind =
    `meter_info(m).kind` (this is `"credit"` for known credit meters and for unknown meters), label =
    `meter_info(m).provider`, `providers=[provider]`, `unit = meter_info(m).unit`, buckets + total as
    above. Credit series are never merged with each other or with fiat.
  - **Order**: fiat first (if present), then the rest sorted by `label`.
  - A meter that only ever produced skipped (malformed) amounts must NOT yield a series.

### 3. `app/api/statistics.py` — `get_statistics(request, months=...)`
- Clamp `months` to `[1, MAX_MONTHS]` (values `<1` → 1; `>MAX_MONTHS` → `MAX_MONTHS`).
- Call `aggregate_statistics(_runs_dir(request), months=<clamped>, now=utc_now())` — import
  `utc_now` from `app.core.ids`.
- Map the resulting `list[Series]` into `StatisticsOut(months=<clamped>, series=[SeriesOut(...)])`
  (and `BucketOut`), returning it. The `months` in the response is the clamped value.

## Constraints / do-nots
- Do NOT edit any test, and do NOT change any frozen signature or response model.
- Do NOT add a dependency, and do NOT read anything but the run records (no network).
- No ElevenLabs/quota handling and no FX conversion here — out of scope for C-5a.
- Keep `ruff` and `mypy --strict` clean; match the tolerant-reading style of `app/core/estimate.py`.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/core/test_meters.py tests/core/test_statistics.py tests/api/test_statistics_api.py -q` → all pass.
- `-m ruff check .`, `-m ruff format --check .`, and `-m mypy sdk app` → clean.
