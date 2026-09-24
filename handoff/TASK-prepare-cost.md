# TASK-prepare-cost — persist prepare-phase spend and count it in Statistics

## Goal

The shared prepare phase can spend real money once per run (before any video), but `_run_prepare` discards the cost the engine aggregates for that phase, so it lands in `events.jsonl` and nowhere durable — invisible to the Statistics tab and to estimation, though it IS budget-gated. Persist the prepare phase's aggregated cost into `request.json` as an optional `prepare_cost` block shaped exactly like a video's `cost` (`{"uncached": {meter: amount}, "actual": {meter: amount}}`), and count its `actual` in `aggregate_statistics`.

Scope note: this increment does the persistence + the Statistics half only. Feeding prepare cost into cost ESTIMATION is a separate follow-on (the per-video Estimate needs a per-run-overhead decision) — do NOT touch `app/core/estimate.py`.

## Files to change

1. `app/core/records.py`
2. `app/core/supervisor.py` (function `_run_prepare`)
3. `app/core/statistics.py`

Do not touch any test or any other module. The frozen contract is `tests/core/test_prepare_cost.py` (+ the stub `tests/stubs/prepare_emits_cost/`).

## The change

### 1. `records.py` — the optional field

- Add `prepare_cost: dict[str, Any] | None = None` to `RequestRecord` (after `forecast`).
- Add `"prepare_cost"` to `REQUEST_OPTIONAL_FIELDS` so it is omitted from `request.json` when `None` (via `_dump_owned`).
- Add a keyword-only `prepare_cost: dict[str, Any] | None = None` parameter to `update_request`, threaded into the `model_copy(update=...)` exactly like `budget`/`forecast` (i.e. `current.prepare_cost if prepare_cost is None else prepare_cost`), so passing it sets it and omitting it preserves the current value.

### 2. `supervisor.py` — capture and persist in `_run_prepare`

`_run_prepare` currently calls `_consume_stdout(...)` and discards all three return values (`_, _, _ = _consume_stdout(...)`). Its second return value is the aggregated `cost` dict (`{"uncached": {...}, "actual": {...}}` or `None`). Capture that cost, and after the prepare phase succeeds (the existing success path, where `result_path` exists and the payload is read), if the cost is not `None`, persist it with `update_request(run_dir, prepare_cost=<cost>)`. `request.json` already exists at this point (created before the prepare phase). Do not persist on the failure/early-return paths (`returncode != 0` or missing result) — those return before success, matching a video's cost handling. The cost is already aggregated from redacted events, so no extra redaction is needed here.

### 3. `statistics.py` — count `prepare_cost["actual"]`

In `aggregate_statistics`, for each counted (non-dry, in-window) run, add the run's `prepare_cost["actual"]` per-meter amounts to the totals with the SAME rules already applied to video actual: quota meters excluded, fiat summed into the `"fiat"` series, other meters standalone, and the same tolerant-amount guards (reject bool, non-`int|float`, `float()` overflow, non-finite, negative). The cleanest shape is to factor the existing per-meter accumulation in the video loop into a small helper (e.g. `_add_amounts(totals, fiat_meters, other_meters, amounts, registry)`) and call it for both the video actual (`_run_actual(run_dir)`) and the prepare actual (`record.prepare_cost["actual"]` when `record.prepare_cost` is a dict and its `"actual"` is a dict). Reading `prepare_cost` from the already-parsed `record` (a `RequestRecord`) is fine — no new file read.

## Constraints

- Behaviour-preserving except for the new field and its counting: a run with no `prepare_cost` behaves exactly as today; the field is absent from `request.json` when unset.
- No new dependency; no change to any frozen signature other than the additive `update_request` parameter and the additive `RequestRecord` field.
- One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_prepare_cost.py` is fully green (RED now).
- `tests/core/test_statistics.py`, `tests/core/test_records.py`, `tests/core/test_forecast_recording.py`, and `tests/integration/` stay green (no regression to the existing request/statistics contracts).
- Full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .`, `-m ruff format --check .`, `-m mypy`.

## Builder notes

Record any tooling friction in `docs/BUILDER_NOTES.md` for the supervisor to route to Bridge Feedback; record anything you learn about the defect or a pitfall there too, for the Issues file.
