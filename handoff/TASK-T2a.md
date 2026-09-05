# TASK T2a — budget circuit-breaker engine (`sfvf._budget`)

**Builder:** Cursor. **Product code only** in `sdk/sfvf/_budget.py`. Do NOT touch `tests/`, `docs/`,
`handoff/`, or any other file. The reviewer contract `tests/sdk/test_budget.py` is FROZEN — do not edit it.

This is the minimal money-safety backstop that must exist before any live paid call (Architecture §5.4,
reserve-then-reconcile, restricted to the safety subset). Pure, file-backed engine. **No wiring** into
`agents.py` / `media/video.py` / the supervisor in this increment — engine only.

## Implement in `sdk/sfvf/_budget.py`

The skeleton already defines the public names (frozen by the contract): `BudgetError`,
`BudgetExceededError`, `KillSwitchEngagedError`, the frozen dataclass `Ceilings(per_run, per_day)`, and
`BudgetGuard(ledger_path, *, ceilings, kill_switch_path=None, now=_default_now)` with methods
`reserve`, `reconcile`, `day_total`, `run_total`. Keep every signature exactly as-is; fill in the bodies.

### Ledger format (JSONL, one JSON object per line)
Each `reserve` appends one line; each `reconcile` appends one line. Fields:
```json
{"ts": "2026-09-05T12:00:00Z", "token": "<hex>", "run_id": "r1", "meter": "openrouter",
 "unit": "EUR", "amount": 0.5, "kind": "reserved", "note": ""}
```
`kind` is `"reserved"` or `"actual"`. `ts` is the injected clock formatted UTC `...Z`
(`now().astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")`). `token` is a fresh `uuid.uuid4().hex` per
reservation; `reconcile` writes an `"actual"` line carrying the **same** token.

### Totals (the core accounting)
For a set of ledger entries, compute the **effective amount per token**: if the token has an `"actual"`
entry, the effective amount is that actual; otherwise it is the open `"reserved"` amount. Never count
both (no double-counting a reconciled reservation).
- `run_total(run_id, meter)`: sum of effective amounts over tokens whose entries match `run_id` **and**
  `meter` (all dates — a run is short-lived).
- `day_total(meter)`: sum of effective amounts over tokens whose entries match `meter` **and** fall on
  the **current UTC calendar day** (`now().astimezone(UTC).date()`). Determine a token's day from its
  `reserved` entry's `ts` date. Entries from other days do not count.

### `reserve(*, run_id, meter, unit, estimate, note="") -> str`
1. If `kill_switch_path` is not None **and** the file exists → raise `KillSwitchEngagedError` (append
   nothing).
2. Compute `projected_day = day_total(meter) + estimate` and `projected_run = run_total(run_id, meter) +
   estimate`. If `meter` is in `ceilings.per_day` and `projected_day > limit` → raise
   `BudgetExceededError` (append nothing). Same for `ceilings.per_run` / `projected_run`. A meter absent
   from a map is unlimited. **Exactly at the ceiling is allowed** (`>` not `>=`); use a tiny tolerance is
   NOT needed — the contract uses values that compare exactly.
3. Otherwise append a `"reserved"` line and return the token.

### `reconcile(token, *, actual, note="") -> None`
Append an `"actual"` line with the given `token` and `actual` amount. (Meter/unit/run_id may be copied
from the matching reserved entry if convenient, or left to what you record — totals key on token; the
contract only checks totals after reconcile. Recording meter/run_id on the actual line is recommended so
the actual is attributable without cross-referencing.)

### Concurrency / durability
The ledger is the cross-process source of truth: the parent and multiple child runner processes may
append concurrently. Make the **read-modify-append critical section** in `reserve` safe across processes,
not just threads:
- Hold a `threading.Lock` (instance-level) for in-process safety, AND
- Take an **OS advisory file lock** on a sidecar lock file (e.g. `<ledger>.lock`) around the
  read-totals-then-append sequence so two processes cannot both pass the ceiling check and append. Use
  `msvcrt.locking` on Windows (`sys.platform == "win32"`) and `fcntl.flock` on POSIX; wrap in a small
  `contextlib.contextmanager` that always releases. Create parent dirs as needed. Reads in `day_total` /
  `run_total` and the append must all parse/write the file defensively (create-if-missing; ignore blank
  lines). Keep it simple and correct; the ledger is expected to stay small.

Never log or embed a secret. mypy-strict clean. **No new third-party dependency** (stdlib only:
`json`, `uuid`, `threading`, `contextlib`, `msvcrt`/`fcntl`, `datetime`, `pathlib`). Touch only
`sdk/sfvf/_budget.py`.

## Acceptance

`tests/sdk/test_budget.py` passes (12 tests): reserve returns a token and appends a `reserved` entry;
missing ledger → zero totals; reserves accumulate into run/day totals; reconcile supersedes the estimate
(no double count); per-run and per-day ceilings raise `BudgetExceededError` and append nothing on denial;
an open reservation is visible to a concurrent reserver (overshoot denied); meters are isolated; exactly
at ceiling is allowed and overshoot denied; kill-switch present raises `KillSwitchEngagedError` and
appends nothing; absent kill-switch file → never engaged; prior-day entries do not count toward today.

## Full local gate (from the worktree venv)

```
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest -q tests/sdk/test_budget.py
```
(The full `pytest` run may show pre-existing `finalize`/`example_workflow` failures from the HyperFrames
toolchain not being installed in this worktree; CI installs it and runs them green. Ignore those.)
