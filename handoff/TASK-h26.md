# TASK-h26 — fold the forecast write into record_event (event-ordered forecasts)

## Goal

Close H26: make the durable `request.forecast[meter]` strictly consistent with the last forecast event appended for that meter, by folding the forecast-accumulator write into `_RunState.record_event` under its single lock hold. Today the append and the accumulator write take the run lock separately, so two videos in one request forecasting the same meter concurrently can leave `request.forecast[meter]` on an earlier event's value while `events.jsonl` shows a later one.

## The one file to change

`app/core/supervisor.py` only. Do not touch any test, any other module, or `docs/`.

## Current code (for orientation)

`_RunState` (around line 133) has a non-reentrant `lock: threading.Lock`, a `forecasts: dict[str, dict]` accumulator, and two methods:

- `record_event(run_dir, event, source)` (line 146): under `self.lock`, appends `_redact_secrets(event, self.secret_values)` to `events.jsonl` via `append_event`.
- `record_forecast(run_dir, *, meter, unit, amount)` (line 150): under `self.lock`, sets `self.forecasts[meter] = {"unit", "amount", "at_utc": format_utc_z(utc_now())}` and calls `update_request(run_dir, forecast=dict(self.forecasts))`.

`_consume_stdout` (around line 810) does, per stdout line: `state.record_event(...)` (line 816), then computes `redacted = _redact_secrets(event, state.secret_values)` (817), and later `parsed_forecast = _parse_forecast_event(redacted)` → `state.record_forecast(...)` (830-833). Those are two separate lock acquisitions — the race window.

`_parse_forecast_event(event)` (line 754) returns `(meter, unit, amount)` for a well-formed forecast event (`t == "forecast"`, non-empty str meter, str unit, finite amount ≥ 0) else `None`.

## The change

1. **Fold the forecast write into `record_event`, under the single existing lock hold.** Inside `record_event`, still under `with self.lock`: compute the redacted event once, append it (as now), then — if `_parse_forecast_event(<redacted event>)` returns a triple — update `self.forecasts[meter] = {"unit": unit, "amount": amount, "at_utc": format_utc_z(utc_now())}` and call `update_request(run_dir, forecast=dict(self.forecasts))`, all before releasing the lock. Parse from the **redacted** event (so a secret in the meter is already `[REDACTED]`, matching today's `_consume_stdout` behaviour and the existing redaction test).

2. **Remove the now-redundant second acquisition in `_consume_stdout`.** Delete the `parsed_forecast = _parse_forecast_event(redacted)` branch and its `state.record_forecast(...)` call (830-833). The forecast is now handled entirely inside the `record_event` call already made at line 816. (Leave the cost-event parsing at 822-829 exactly as it is — that is a separate concern and stays.)

3. **Do not leave a deadlock or a dead second writer.** `self.lock` is a plain non-reentrant `threading.Lock`, so `record_event` (holding the lock) must NOT call `record_forecast` (which re-acquires it) — inline the accumulator logic instead. Since `record_forecast` then has no caller, remove the `record_forecast` method. (A leftover `record_forecast` still called anywhere would re-introduce the exact two-lock race H26 fixes.)

## Constraints

- Behaviour-preserving except for the fold: the forecast block's shape (`{meter: {unit, amount, at_utc}}`), latest-per-meter-wins, distinct-meter accumulation, the malformed-forecast skip, and secret redaction are all unchanged. This is a concurrency-correctness fix, not a feature change.
- No new dependency, no new public signature, no test edits. `record_event`'s signature stays the same.
- One paragraph is one line in any Markdown you write (no hard wraps).

## Done when

- `tests/core/test_forecast_ordering.py` is fully green (it is RED now — the fold is what turns it green), including `test_concurrent_same_meter_forecasts_match_the_last_event`.
- `tests/core/test_forecast_recording.py` and `tests/core/test_secret_redaction.py` stay green (the end-to-end forecast + redaction contracts).
- The full suite passes: `.\.venv\Scripts\python.exe -m pytest -q`.
- Gate clean: `.\.venv\Scripts\python.exe -m ruff check .` and `-m ruff format --check .` and `-m mypy`.

## Builder notes

If you hit tooling friction (a check that will not run, a flaky harness), record it in `docs/BUILDER_NOTES.md` for the supervisor to route to Bridge Feedback; if you learn something about the defect or a pitfall while fixing it, record that too — the supervisor sorts it into the project's Issues file at the next reflection point.
