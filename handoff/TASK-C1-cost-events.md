# TASK C-1 — cost events + per-video cost recording (closes H10)

## Goal (one sentence)
Emit a `cost` event on each real priced OpenRouter call and have the supervisor aggregate cost events
into `video.json`'s `cost` block — turning spend from a log line into a recorded meter.

## Frozen contract (already committed — do not edit any test)
- `tests/sdk/test_cost_events.py`: a non-dry `agents.llm`/`agents.research` call whose response carries
  a usable `usage.cost` emits exactly one event
  `{"t":"cost","meter":"openrouter","unit":"usd","amount":<cost>,"cached":false}`; a missing/malformed
  `usage.cost` and `dry_run` emit none.
- `tests/core/test_cost_recording.py` + `tests/stubs/emits_cost/`: the supervisor aggregates `cost`
  events into `video.json` `cost = {"actual": {meter: amount}, "uncached": {meter: amount}}` — each
  event adds to `uncached[meter]`, and also to `actual[meter]` when `cached` is false; a meter shows in
  `actual` only if it had a non-cached cost, in `uncached` if it had any cost; no cost events → no
  `cost` block (`None`).

## Changes

### 1. `sdk/sfvf/agents.py` — emit the cost event
In `_post_chat_completion` (the shared helper used by both `llm` and `research`), where it already
computes `cost = _usage_cost(data)` for the reconcile: when `cost is not None`, emit
`ctx.emit({"t": "cost", "meter": "openrouter", "unit": "usd", "amount": cost, "cached": False})`.
- Emit it once per call, here in the shared helper (do NOT also emit in `llm`/`research`).
- Emit independent of budget config (surface cost even when the reconcile is a no-op). Keep the
  existing `ctx.log(...)` lines and the reconcile as they are. `dry_run` never reaches this helper.

### 2. `app/core/supervisor.py` — aggregate cost events into the video record
- In `_consume_stdout`, alongside the existing result capture, accumulate `cost` events into two
  per-meter dicts. For each event with `event.get("t") == "cost"`, defensively read: `meter` (a
  non-empty `str`), `amount` (a finite, non-negative `int`/`float`, not `bool`), `cached` (a `bool`,
  default `False`). Silently ignore a malformed cost event (tolerant parsing, §8). Add `amount` to
  `uncached[meter]`; if not `cached`, also add to `actual[meter]`.
- Change `_consume_stdout` to return `(captured, cost)` where `cost` is
  `{"actual": {...}, "uncached": {...}}` (omitting empty sub-dicts is fine, but include the block when
  there was at least one valid cost event) or `None` when there were none.
- `_run_one_video`: unpack `captured, cost = _consume_stdout(...)` and pass `cost=cost` into the
  `VideoRecord(...)` written on the completion path (the `status == "complete"` write). Leave the
  `except`-branch failure write as-is.
- `_run_prepare` calls `_consume_stdout(...)` as a bare statement and discards the result today — a
  tuple return leaves that untouched; do not add cost handling to prepare in this increment.
- `VideoRecord.cost` and `VIDEO_OPTIONAL_FIELDS` already exist in `app/core/records.py` — no records
  schema change; just populate the field.

## Constraints / do-nots
- Do NOT edit any test. Do NOT touch the budget ledger/gate, the on-disk record schema, or Higgsfield
  (its per-video cost is out of scope — no per-call cost from the API, H20).
- Match surrounding style; keep `ruff` and `mypy --strict` clean.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/sdk/test_cost_events.py tests/core/test_cost_recording.py tests/core/test_supervisor.py tests/integration/test_budget_gate.py -q` → all pass (the new contracts go green; existing supervisor/budget tests stay green).
- `-m ruff check .` and `-m mypy sdk app` → clean.
