# TASK C-2 — forecasts (§5.4a): ctx.forecast + supervisor recording

## Goal (one sentence)
Let a workflow declare, mid-run, what the remainder will cost — `ctx.forecast(...)` emits a forecast
event and the supervisor records it into `request.json` as a soft (non-blocking) reservation.

## Frozen contract (already committed — do not edit any test)
- `tests/sdk/test_forecast.py`: `ctx.forecast(meter, unit, amount, note=None)` emits exactly
  `{"t":"forecast","meter":...,"unit":...,"amount":...[,"note":...]}`; `note` omitted when absent.
- `tests/core/test_forecast_recording.py` + stubs: the supervisor records forecast events into
  `request.json` `forecast = {meter: {unit, amount, at_utc}}`; the latest forecast for a meter
  supersedes earlier ones; distinct meters accumulate; no forecast events → no `forecast` block; a
  secret surfacing in a forecast (e.g. the meter) is redacted (`[REDACTED]`, never the raw value).

## Changes

### 1. `sdk/sfvf/emit.py` — a `forecast` helper (mirror `decision`)
```
def forecast(meter: str, unit: str, amount: float, *, note: str | None = None) -> None:
    event = {"t": "forecast", "meter": meter, "unit": unit, "amount": amount}
    if note is not None:
        event["note"] = note
    emit(event)
```

### 2. `sdk/sfvf/context.py` — `ctx.forecast` (mirror `ctx.decision`)
```
def forecast(self, meter: str, unit: str, amount: float, note: str | None = None) -> None:
    forecast(meter, unit, amount, note=note)   # the emit.forecast helper
```
(Import it alongside the other emit helpers already imported in context.py.)

### 3. `app/core/records.py` — `update_request` carries a forecast block
Add keyword-only `forecast: dict[str, Any] | None = None`; in the `model_copy(update=...)` set
`"forecast": current.forecast if forecast is None else forecast`. `RequestRecord.forecast` and its
entry in `REQUEST_OPTIONAL_FIELDS` already exist — no schema change.

### 4. `app/core/supervisor.py` — record forecasts (soft reservation)
- `_RunState`: add `forecasts: dict[str, dict[str, Any]] = field(default_factory=dict)` and a
  lock-guarded method:
  ```
  def record_forecast(self, run_dir, *, meter, unit, amount) -> None:
      with self.lock:
          self.forecasts[meter] = {"unit": unit, "amount": amount,
                                   "at_utc": format_utc_z(utc_now())}
          update_request(run_dir, forecast=dict(self.forecasts))
  ```
- Add a tolerant `_parse_forecast_event(event) -> tuple[str, str, float] | None` mirroring
  `_parse_cost_event`: require `t == "forecast"`, `meter` a non-empty `str`, `unit` a `str`, `amount`
  a finite non-negative number that is not `bool`; **guard `float(amount)` with
  `try/except (OverflowError, ValueError): return None`** (the C-1 lesson — an oversized int must be
  ignored, not crash consumption); return `None` for anything malformed.
- In `_consume_stdout`, where the `redacted` event is already computed (for result/cost), also parse
  the forecast from that **redacted** event (never the raw event — the C-1 redaction lesson: this is
  a write path) and, when valid, call `state.record_forecast(run_dir, meter=…, unit=…, amount=…)`.

## Constraints / do-nots
- Do NOT edit any test. Do NOT touch the budget ledger/gate or the cost path from C-1. The forecast is
  a soft, non-blocking reservation here; the atomic pre-flight that acts on it is C-3.
- Redact before recording; tolerate malformed/oversized events (absorb, don't crash — §8).
- Keep `ruff` and `mypy --strict` clean; match surrounding style.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_forecast.py tests/core/test_forecast_recording.py tests/core/test_records.py tests/core/test_supervisor.py -q` → all pass.
- `-m ruff check .` and `-m mypy sdk app` → clean.
