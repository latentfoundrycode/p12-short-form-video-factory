from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import PurePosixPath

from app.learning.engine import LearningInput, OptimizeFn, ProposedEdit


class OptimizerError(Exception):
    """Raised on any unparseable or out-of-bounds optimiser response."""


type CompleteFn = Callable[[list[dict[str, str]]], str]


_FENCE = re.compile(
    r"\A\s*```(?:json)?\s*\n?(.*?)\n?```\s*\Z",
    re.DOTALL | re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "You are a SkillOpt-derived optimiser. You revise a workflow's instruction "
    "files so future videos better match the user's judgement.\n"
    "The quality answers are the user's own words about what they wanted — treat "
    "them as AUTHORITATIVE directives, not as evidence to second-guess. Encode "
    "the user's stated preferences faithfully: if a user says a video must do "
    "something (or must not), write a rule that says exactly that. Do NOT "
    "override, soften, or invert a stated preference because you disagree with "
    "it or think it is bad practice — your job is to capture what the user "
    "wants, not to impose your own taste.\n"
    "Propose edits ONLY to files under rules/ or skills/. Do not edit "
    "criteria or any other path.\n"
    "Reply with a JSON object of this exact shape: "
    '{"edits": [{"path": "...", "content": "..."}, ...]}. '
    "path is the workflow-relative POSIX path (e.g. rules/tone.md) and "
    'content is the FULL new file body. Return {"edits": []} if nothing '
    "should change."
)


def _files_block(title: str, files: dict[str, str]) -> str:
    lines = [title]
    if not files:
        lines.append("(none)")
        return "\n".join(lines)
    for name, body in files.items():
        lines.append(f"### {name}\n{body}")
    return "\n\n".join(lines)


def build_optimizer_messages(learning_input: LearningInput) -> list[dict[str, str]]:
    user = "\n\n".join(
        [
            f"Workflow id: {learning_input.workflow_id}",
            _files_block(
                "## Editable rules (you may edit these)",
                learning_input.rules,
            ),
            _files_block(
                "## Editable skills (you may edit these)",
                learning_input.skills,
            ),
            _files_block(
                "## Read-only criteria (consult only; do not edit)",
                learning_input.criteria,
            ),
            "## Quality evidence (answers, rankings, accept/reject)\n"
            + json.dumps(learning_input.labels, indent=2),
        ]
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def _strip_fence(text: str) -> str:
    match = _FENCE.match(text)
    if match is not None:
        return match.group(1).strip()
    return text.strip()


def _validate_path(raw_path: str) -> None:
    if "\\" in raw_path or ":" in raw_path:
        raise OptimizerError(f"edit path is outside rules/ and skills/: {raw_path}")
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or len(path.parts) < 2
        or path.parts[0] not in {"rules", "skills"}
    ):
        raise OptimizerError(f"edit path is outside rules/ and skills/: {raw_path}")


def parse_optimizer_response(text: str) -> list[ProposedEdit]:
    try:
        payload = json.loads(_strip_fence(text))
    except json.JSONDecodeError as exc:
        raise OptimizerError("optimiser response is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise OptimizerError("optimiser response has the wrong shape")
    raw_edits = payload.get("edits")
    if not isinstance(raw_edits, list):
        raise OptimizerError("optimiser response is missing an edits array")

    edits: list[ProposedEdit] = []
    for entry in raw_edits:
        if not isinstance(entry, dict):
            raise OptimizerError("edit entry must be an object")
        path = entry.get("path")
        content = entry.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            raise OptimizerError("edit path and content must be strings")
        _validate_path(path)
        edits.append(ProposedEdit(path=path, content=content))
    return edits


def make_optimizer(complete: CompleteFn) -> OptimizeFn:
    def optimize(learning_input: LearningInput) -> list[ProposedEdit]:
        return parse_optimizer_response(
            complete(build_optimizer_messages(learning_input)),
        )

    return optimize
