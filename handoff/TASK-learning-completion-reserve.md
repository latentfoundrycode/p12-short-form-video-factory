# TASK — fix the budget reserve/release taxonomy in learning completion

## Why
`app/learning/completion.py::make_openrouter_completion` has the same reserve-leak class that the
`agents.py` inc0 fix (PR #144) corrected. Its `unbilled` flag starts **False**, and is set True only on
the explicit non-2xx / 429-exhausted paths. So a failure BEFORE any request is dispatched — e.g.
`client_factory()` raising, or anything between `guard.reserve(...)` and the first `client.post` —
leaves `unbilled=False`, so the `finally` never releases and the reservation **leaks** toward the
`learning` ceiling for a call that never dispatched or billed.

The correct taxonomy (already merged in `sdk/sfvf/agents.py::_post_chat_completion`): default to
**unbilled=True** (a pre-dispatch failure releases), and flip to **False only just before the dispatch**
(a transport failure from there is ambiguous → retain), resetting True on the confirmed-unbilled status
paths.

A frozen RED contract is committed (HEAD): `tests/integration/test_learning_completion.py` —
`test_a_pre_dispatch_failure_releases_the_reserve` (RED) and
`test_a_transport_error_after_dispatch_retains_the_reserve` (guard, already green).

## Change (one file) — `app/learning/completion.py`
In `make_openrouter_completion`'s `complete()` (the reserve/try/finally around the OpenRouter call),
adjust ONLY the `unbilled` bookkeeping to mirror `agents.py`:
1. Initialise `unbilled = True` (was `False`) — nothing is dispatched yet, so a failure up to the first
   dispatch releases.
2. As the FIRST statement inside the `for attempt in range(_MAX_ATTEMPTS):` loop, before `client.post`,
   add `unbilled = False` — about to dispatch; an ambiguous transport failure from here retains.
3. On the 429 branch, set `unbilled = True` before the `sleep`/`continue` (a 429 response is not billed).
   The existing `unbilled = True` on the other non-2xx branch and on the `else` (rate-limited-after-
   retries) stay.
The 200 path (parse `usage.cost`, `guard.reconcile(token, actual=cost)` when present, extract content)
stays as-is: `unbilled` remains False there, so a post-200 parse/shape failure RETAINS (the call was
billed) — matching agents.py and the frozen guard. The `finally: if unbilled: guard.reconcile(token,
actual=0.0)` stays as-is.

Net outcomes after the fix:
- pre-dispatch failure (client_factory raises) → unbilled=True → release $0. (the bug)
- transport error at/after dispatch → unbilled=False → retain.
- non-2xx status / 429-exhausted → unbilled=True → release.
- 200 then malformed/short body → unbilled=False → retain (billed).
- 200 success → reconcile the real `usage.cost`; finally no-op.

## Scope
Only `app/learning/completion.py`. Do NOT change the SDK, `agents.py`, `_budget.py`, the reserve/
reconcile calls' arguments, or the frozen tests. No new dependencies. Never read/log the api key.
Create no notes/docs files.

## Acceptance
- `PYTHONPATH=sdk python -m pytest tests/integration/test_learning_completion.py -q` → all pass (the two
  new taxonomy tests plus every existing completion test — the success/cost-metering/429/non-2xx/
  fail-closed/kill-switch/missing-key cases must stay green).
- `ruff check app tests` and `ruff format --check app tests` clean; `.\.venv\Scripts\python.exe -m mypy`
  clean if it runs in your env.
