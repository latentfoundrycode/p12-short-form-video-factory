from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import Context

_GATE_POLL_SECONDS = 0.05
# The stop sentinel is part of the workflow/chassis wire protocol.
_STOP_SENTINEL = ".stop"


class GateRejected(Exception):  # noqa: N818 - public SDK contract name
    """Raised when a workflow gate is rejected or its run is stopped."""


def _finish(decision: object, shape: str) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("gate decision must be a JSON object")

    result = dict(decision)
    choice = result.get("choice")
    if not isinstance(choice, str):
        raise ValueError("gate decision must contain a string 'choice'")
    if choice == "reject":
        note = result.get("note")
        message = "gate rejected" if note in (None, "") else f"gate rejected: {note}"
        raise GateRejected(message)

    if shape == "selection":
        for key in ("keep", "redo"):
            values = result.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f"gate decision '{key}' must be a list")
            result[key] = [str(value) for value in values]
        note = result.get("note", "")
        result["note"] = "" if note is None else str(note)

    return result


def _bypass_decision(
    shape: str,
    items: list[Any] | None,
    on_bypass: str | None,
) -> dict[str, Any]:
    if shape == "approval":
        if on_bypass in (None, "approve"):
            return {"choice": "approve"}
        if on_bypass == "reject":
            return {"choice": "reject"}
        raise ValueError("approval gate on_bypass must be 'approve' or 'reject'")

    if shape == "choice":
        if on_bypass is None:
            raise ValueError("choice gate requires on_bypass")
        if items is None or on_bypass not in items:
            raise ValueError("choice gate on_bypass must be one of its options")
        return {"choice": on_bypass}

    if shape == "selection":
        if on_bypass is None:
            raise ValueError("selection gate requires on_bypass")
        if on_bypass == "approve-all":
            return {
                "choice": "approve",
                "keep": [item["id"] for item in items or []],
                "redo": [],
                "note": "",
            }
        if on_bypass == "reject":
            return {"choice": "reject"}
        raise ValueError("selection gate on_bypass must be 'approve-all' or 'reject'")

    raise ValueError(f"unknown gate shape: {shape}")


def run_gate(
    ctx: Context,
    family: str,
    *,
    prompt: str,
    payload: Any,
    options: list[str] | None,
    items: list[dict[str, Any]] | None,
    select: str | None,
    on_bypass: str | None,
) -> dict[str, Any]:
    if options is not None and items is not None:
        raise ValueError("gate options and items are mutually exclusive")
    if select is not None and select != "subset":
        raise ValueError("gate select may only be 'subset'")
    if select is not None and items is None:
        raise ValueError("gate select requires items")
    if items is not None and select != "subset":
        raise ValueError("gate items require select='subset'")
    if items is not None:
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise ValueError("each gate item must be an object with a string 'id'")

    shape = "choice" if options is not None else "selection" if items is not None else "approval"
    occurrence = ctx._gate_counts.get(family, 0)
    ctx._gate_counts[family] = occurrence + 1
    token = f"{family}-{occurrence}"
    response_path = ctx.video_dir / "gates" / f"{token}.json"

    if response_path.is_file():
        decision = json.loads(response_path.read_text(encoding="utf-8"))
        return _finish(decision, shape)

    if ctx.gates_auto:
        bypass_items: list[Any] | None = options if shape == "choice" else items
        decision = _bypass_decision(shape, bypass_items, on_bypass)
        response_path.parent.mkdir(parents=True, exist_ok=True)
        response_path.write_text(json.dumps(decision), encoding="utf-8")
        return _finish(decision, shape)

    event: dict[str, Any] = {
        "t": "gate",
        "family": family,
        "token": token,
        "shape": shape,
        "prompt": prompt,
    }
    if payload is not None:
        event["payload"] = payload
    if options is not None:
        event["options"] = options
    if items is not None:
        event["items"] = items
    if on_bypass is not None:
        event["on_bypass"] = on_bypass
    ctx.emit(event)

    while not response_path.is_file():
        if (ctx.video_dir / _STOP_SENTINEL).exists():
            raise GateRejected("run stopped at gate")
        time.sleep(_GATE_POLL_SECONDS)

    decision = json.loads(response_path.read_text(encoding="utf-8"))
    return _finish(decision, shape)


def gate_attempts(ctx: Context, family: str, *, item: str | None = None) -> int:
    gates_dir = ctx.video_dir / "gates"
    if not gates_dir.is_dir():
        return 0

    attempts = 0
    for response_path in gates_dir.glob(f"{family}-*.json"):
        try:
            decision = json.loads(response_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(decision, dict) or not isinstance(decision.get("choice"), str):
            continue
        redo = decision.get("redo", [])
        if not isinstance(redo, list) or not all(isinstance(value, str) for value in redo):
            redo = []
        if item is not None:
            attempts += item in redo
        elif decision["choice"] == "reject" or redo:
            attempts += 1
    return attempts
