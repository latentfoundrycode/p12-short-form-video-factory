"""T2b-2c contract: the runner signals a budget denial distinctly to the supervisor.

When a workflow entry aborts because the budget guard refused a paid call (a
`sfvf._budget.BudgetError` — a ceiling breach or the kill-switch), the child runner must tell the
parent WHY, so the supervisor can label the run `stopped-budget` (a clean, actionable stop) instead
of a generic `failed`. The signal is redaction-independent and two-fold: it exits with
`runner.EXIT_BUDGET_DENIED`
(distinct from 1 = generic failure and 0 = success) AND the emitted error log carries
`reason == "budget"`. A budget error anywhere in the raised exception's cause/context chain counts,
so a workflow that catches and re-raises still reports budget. Any other failure keeps the existing
exit code 1 with no budget reason. No network, no real spend; everything lives under tmp_path.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sfvf import runner

_WORKFLOW_TOML = """\
[workflow]
id = "t"
name = "T"
version = "1.0.0"
entrypoint = "main:entrypoint"
sdk = "1"
"""


def _events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def _errors(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    return [e for e in _events(capsys) if e.get("t") == "log" and e.get("level") == "error"]


def _run_entry(tmp_path: Path, body: str) -> int:
    wf = tmp_path / "wf"
    wf.mkdir()
    (wf / "workflow.toml").write_text(_WORKFLOW_TOML, encoding="utf-8")
    (wf / "main.py").write_text(body, encoding="utf-8")
    video = tmp_path / "video"
    video.mkdir()
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "settings": {},
                "paths": {
                    "video": str(video),
                    "artifacts": str(video / "artifacts"),
                    "steps": str(video / ".steps"),
                    "shared": str(video),
                },
            }
        ),
        encoding="utf-8",
    )
    return runner.main(["--workflow", str(wf), "--context", str(context), "--entry", "entrypoint"])


def test_budget_exit_code_is_distinct_from_success_and_generic_failure() -> None:
    assert runner.EXIT_BUDGET_DENIED not in (0, 1)


def test_budget_denial_exits_budget_code_and_tags_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        "from sfvf._budget import BudgetExceededError\n"
        "def entrypoint(ctx):\n"
        "    raise BudgetExceededError('per-day ceiling reached')\n"
    )
    assert _run_entry(tmp_path, body) == runner.EXIT_BUDGET_DENIED
    errors = _errors(capsys)
    assert errors and errors[-1].get("reason") == "budget"


def test_kill_switch_denial_is_also_a_budget_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        "from sfvf._budget import KillSwitchEngagedError\n"
        "def entrypoint(ctx):\n"
        "    raise KillSwitchEngagedError('operator kill-switch')\n"
    )
    assert _run_entry(tmp_path, body) == runner.EXIT_BUDGET_DENIED
    assert _errors(capsys)[-1].get("reason") == "budget"


def test_budget_error_wrapped_in_the_cause_chain_is_detected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A workflow that catches the refusal and re-raises still aborted BECAUSE of the budget denial —
    # the cause chain carries the BudgetError, so the reported reason is still budget.
    body = (
        "from sfvf._budget import BudgetExceededError\n"
        "def entrypoint(ctx):\n"
        "    try:\n"
        "        raise BudgetExceededError('ceiling')\n"
        "    except BudgetExceededError as exc:\n"
        "        raise RuntimeError('step failed') from exc\n"
    )
    assert _run_entry(tmp_path, body) == runner.EXIT_BUDGET_DENIED
    assert _errors(capsys)[-1].get("reason") == "budget"


def test_generic_failure_keeps_exit_one_and_no_budget_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "def entrypoint(ctx):\n    raise ValueError('boom')\n"
    assert _run_entry(tmp_path, body) == 1
    errors = _errors(capsys)
    assert errors and "reason" not in errors[-1]


def test_success_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = "def entrypoint(ctx):\n    return None\n"
    assert _run_entry(tmp_path, body) == 0
    assert _errors(capsys) == []
