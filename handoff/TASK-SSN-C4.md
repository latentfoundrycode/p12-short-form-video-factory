# TASK-SSN-C4 — Approval gate before spending on media

## Context

You are the builder for the Sensational Science News (SSN) workflow. This task adds the owner's
approval gate to `run()`: after the (cheap) narration script is written, present the plan for approval
BEFORE running the media steps (speech / render / finalize). On approval the video proceeds; on
rejection the gate raises and this video ends (the chassis runner records it and lets sibling videos
continue). Scheduled/unattended runs set `gates_auto`, and the gate is declared `on_bypass="approve"`
so it auto-approves without a human — that bypass is provided by the SDK gate runtime; you only make
the call.

## Scope — edit ONLY this file

- `workflows/sensational-science-news/main.py`

Do NOT modify any test, SDK file, other workflow, `workflow.toml`, `requirements.txt`, or
dependencies. No new imports. Stay inside this checkout (`Workspace/`).

## The frozen tests you must make green (do not edit them)

- `tests/integration/test_ssn_gate.py` (2 tests). Read them first; they are the contract.

## What to build

In `run()`, insert an approval gate BETWEEN the script and the media. Concretely, after this existing
line:

```python
    script = step.value
    narration = _narration_text(script)
```

and BEFORE the `ctx.step("speech", ...)` block, add:

1. Compute a best-effort cost estimate for the paid work needed to complete this video, as a float
   `estimated_cost`. Use `ctx.budget_estimate(meter)` for any paid meter the workflow will spend on;
   if the workflow has no configured paid meters at this stage (the current media steps are local),
   default to `0.0`. (This field exists so the owner sees the spend they are approving; it will carry
   real figures once paid media lands in a later stage. Keep it a plain float, never None.)

2. Call the gate:

```python
    ctx.gate(
        "approve-plan",
        prompt=f"Approve the plan for video {ctx.video_index}: {subject!r}?",
        payload={
            "subject": subject,
            "script": narration,
            "estimated_cost_usd": estimated_cost,
        },
        on_bypass="approve",
    )
```

Notes:
- `payload["script"]` MUST be the narration (the cleaned spoken text `narration`), not the raw LLM
  output — that is what the owner judges and what becomes the video.
- The gate family MUST be exactly `"approve-plan"`.
- Do NOT wrap the gate in try/except. On rejection `ctx.gate` raises `sfvf.gate.GateRejected`; let it
  propagate out of `run()` — the chassis runner turns that into "this video ended" and continues the
  other videos. On approval `ctx.gate` returns a decision dict; you can ignore the return value.
- Everything after the gate (speech, render, captions, finalize, the returned `Result`) stays exactly
  as it is now. The gate must sit before the `ctx.step("speech", ...)` block so a rejection spends
  nothing on media.

## Done when (run from Workspace/ with the repo venv)

- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_gate.py -q` — both pass:
  - `test_run_gates_plan_after_script_before_media` (gate called with family `approve-plan` and a
    payload carrying subject + script + a numeric `estimated_cost_usd`, and media runs only after it),
  - `test_run_gate_reject_aborts_before_media` (a rejecting gate raises `GateRejected` and no media
    runs).
- `./.venv/Scripts/python.exe -m pytest tests/integration/test_ssn_script.py tests/integration/test_ssn_prepare.py tests/registry/test_ssn_workflow.py tests/integration/test_ssn_workflow_dry_run.py -q` — still green (the C1 dry-run pipeline still renders; note the dry-run pipeline runs with gates auto-approved, so it must still complete end to end).
- `./.venv/Scripts/python.exe -m ruff check workflows/sensational-science-news` and `./.venv/Scripts/python.exe -m ruff format --check .` — clean.
- `./.venv/Scripts/python.exe -m mypy` — no NEW errors from `main.py` (a pre-existing PIL error in `sdk/sfvf/media/web.py` is unrelated).

Print the new gate block and one line confirming where it sits relative to the script and speech steps.
