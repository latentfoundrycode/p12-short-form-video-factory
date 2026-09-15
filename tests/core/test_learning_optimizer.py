"""G-7a contract: the SkillOpt-derived learning optimiser core (Architecture §5.11).

§5.11: "gather every `video.json` containing quality answers since the last learning run, load that
workflow's criteria files together with its current rules and skills, and run the SkillOpt-derived
optimiser to propose bounded edits." and: "**Only files inside `workflows/<id>/rules/` and
`workflows/<id>/skills/` may be modified.** Any proposal touching a path outside that is rejected
outright."

This increment builds the optimiser's pure, UNPAID core: it turns a `LearningInput` into chat
messages, and parses a chat completion back into bounded `ProposedEdit`s. The paid OpenRouter call
(auth, the SEPARATE learning budget meter, cost metering) is injected as `complete` and wired in a
later increment — here it is always a stub, so no network call and no spend can occur.
`make_optimizer` returns a plain `OptimizeFn`, so its result drops straight into
`run_learning(optimize=...)` (G-5).
"""

from __future__ import annotations

import json

import pytest

from app.learning.engine import LearningInput, ProposedEdit
from app.learning.optimizer import (
    OptimizerError,
    build_optimizer_messages,
    make_optimizer,
    parse_optimizer_response,
)


def _input() -> LearningInput:
    return LearningInput(
        workflow_id="explainer",
        labels=[
            {
                "run_id": "r1",
                "video_index": 0,
                "answers": {"hook": "opened too slowly"},
                "rankings": {"hook": 2},
                "accepted": False,
            },
        ],
        criteria={"criteria.md": "Videos must earn the first three seconds."},
        rules={"tone.md": "---\nversion: 3\n---\nBe concrete."},
        skills={"hooks.md": "# Hooks\nOpen on motion."},
    )


def test_messages_carry_roles_and_workflow_data() -> None:
    messages = build_optimizer_messages(_input())
    assert isinstance(messages, list) and len(messages) >= 2
    assert all(set(m) == {"role", "content"} for m in messages)
    roles = [m["role"] for m in messages]
    assert roles[0] == "system"  # the optimiser's instructions lead
    assert "user" in roles
    blob = "\n".join(m["content"] for m in messages)
    # the model must see the editable files, the read-only criteria, and the quality evidence
    assert "tone.md" in blob and "hooks.md" in blob
    assert "criteria.md" in blob or "earn the first three seconds" in blob
    assert "opened too slowly" in blob  # a quality answer value is included
    assert "explainer" in blob


def test_system_prompt_encodes_user_preferences_faithfully() -> None:
    # The optimiser must translate the user's stated preferences into rules FAITHFULLY — not
    # editorialise or invert them. A user's "the video must state the date" has to become a rule
    # that states the date, never its opposite. Pin that the standing instruction says so.
    system = build_optimizer_messages(_input())[0]["content"].lower()
    assert "faithful" in system  # encode the user's stated preferences faithfully
    assert "invert" in system or "override" in system  # and never override/invert them


def test_parse_object_with_edits() -> None:
    text = json.dumps(
        {
            "edits": [
                {"path": "rules/tone.md", "content": "---\nversion: 3\n---\nOpen on an object."},
                {"path": "skills/hooks.md", "content": "# Hooks\nStart mid-motion."},
            ]
        }
    )
    edits = parse_optimizer_response(text)
    assert all(isinstance(e, ProposedEdit) for e in edits)
    assert [e.path for e in edits] == ["rules/tone.md", "skills/hooks.md"]
    assert "Open on an object." in edits[0].content


def test_parse_tolerates_code_fenced_json() -> None:
    inner = json.dumps({"edits": [{"path": "rules/tone.md", "content": "New."}]})
    edits = parse_optimizer_response("```json\n" + inner + "\n```")
    assert len(edits) == 1 and edits[0].path == "rules/tone.md"


def test_parse_empty_edits_is_a_noop() -> None:
    assert parse_optimizer_response(json.dumps({"edits": []})) == []


def test_parse_rejects_path_outside_rules_and_skills() -> None:
    # §5.11: any proposal touching a path outside rules/ or skills/ is rejected outright.
    text = json.dumps({"edits": [{"path": "criteria/criteria.md", "content": "hacked"}]})
    with pytest.raises(OptimizerError):
        parse_optimizer_response(text)


def test_parse_rejects_traversal_and_absolute_paths() -> None:
    for bad in [
        "rules\\..\\evil.md",
        "rules/../../evil.md",
        "/etc/passwd",
        "C:\\evil.md",
        "rules",  # fewer than two parts
    ]:
        with pytest.raises(OptimizerError):
            parse_optimizer_response(json.dumps({"edits": [{"path": bad, "content": "x"}]}))


def test_parse_rejects_malformed_json() -> None:
    with pytest.raises(OptimizerError):
        parse_optimizer_response("not json at all")


def test_make_optimizer_calls_complete_once_and_parses() -> None:
    seen: list[list[dict[str, str]]] = []

    def complete(messages: list[dict[str, str]]) -> str:
        seen.append(messages)
        return json.dumps({"edits": [{"path": "rules/tone.md", "content": "Improved."}]})

    optimize = make_optimizer(complete)
    result = optimize(_input())
    assert len(seen) == 1  # the injected completion is called exactly once
    assert seen[0] == build_optimizer_messages(_input())  # with the built messages
    assert [e.path for e in result] == ["rules/tone.md"]
    assert result[0].content == "Improved."
