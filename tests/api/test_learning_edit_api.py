"""#3 contract: the in-app rules/skills editor's API (Architecture §5.11, PRD §8.5).

The Learning tab lets the user open a workflow's own instruction files, edit one by hand, and save
it. Two endpoints back that surface:

`GET /api/learning/{workflow_id}/instructions` -> `{"instructions": [{path, content}]}` — every
`rules/*.md` and `skills/*.md` file the workflow owns, rules before skills, each path workflow-
relative POSIX (e.g. `rules/tone.md`).

`PUT /api/learning/{workflow_id}/instructions` with `{path, content}` -> `{path, version}` — saves
one edit through the SAME archive-and-version-bump path acceptance uses (§5.11): the prior file
moves to `archive/` keyed by its version and the frontmatter `version` increments. Only an existing
file under `rules/` or `skills/` may be saved; anything else is refused. Global instructions are
never touched.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

FACTORS = '[[quality_factors]]\nkey = "hook"\nquestion = "Did it hook you?"'


def _client(tmp_path: Path, extra_files: dict[str, str] | None = None) -> tuple[TestClient, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    workflow_dir = write_plugin(
        workflows,
        "explainer",
        minimal_toml("explainer", extra=FACTORS),
        extra_files=extra_files,
    )
    client = TestClient(
        create_app(
            workflows_dir=workflows,
            runs_dir=tmp_path / "runs",
            learning_state_dir=tmp_path / "learning-state",
            learning_staging_dir=tmp_path / "staging",
        )
    )
    return client, workflow_dir


def test_list_returns_rules_and_skills_with_content(tmp_path: Path) -> None:
    client, _ = _client(
        tmp_path,
        extra_files={
            "rules/tone.md": "---\nversion: 2\n---\nBe concrete.",
            "skills/composition.md": "# Composition\nUse the safe zone.",
        },
    )
    response = client.get("/api/learning/explainer/instructions")
    assert response.status_code == 200
    instructions = response.json()["instructions"]
    assert [i["path"] for i in instructions] == ["rules/tone.md", "skills/composition.md"]
    assert "Be concrete." in instructions[0]["content"]
    assert "Use the safe zone." in instructions[1]["content"]


def test_list_empty_when_no_instruction_files(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    response = client.get("/api/learning/explainer/instructions")
    assert response.status_code == 200
    assert response.json()["instructions"] == []


def test_list_404_for_unknown_workflow(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/api/learning/nope/instructions").status_code == 404


def test_save_archives_prior_and_bumps_version(tmp_path: Path) -> None:
    client, workflow_dir = _client(
        tmp_path, extra_files={"rules/tone.md": "---\nversion: 2\n---\nBe concrete."}
    )
    response = client.put(
        "/api/learning/explainer/instructions",
        json={"path": "rules/tone.md", "content": "---\nversion: 2\n---\nOpen on an object."},
    )
    assert response.status_code == 200
    assert response.json() == {"path": "rules/tone.md", "version": 3}
    live = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "Open on an object." in live
    assert "version: 3" in live
    archived = list((workflow_dir / "archive").rglob("*.md"))
    assert len(archived) == 1
    assert "Be concrete." in archived[0].read_text(encoding="utf-8")
    assert "v2" in archived[0].name


def test_save_404_when_file_does_not_exist(tmp_path: Path) -> None:
    # The editor saves files the user opened from the list; a path with no live file is refused.
    client, workflow_dir = _client(tmp_path)
    response = client.put(
        "/api/learning/explainer/instructions",
        json={"path": "rules/tone.md", "content": "New."},
    )
    assert response.status_code == 404
    assert not (workflow_dir / "rules" / "tone.md").exists()


def test_save_rejects_path_outside_rules_and_skills(tmp_path: Path) -> None:
    client, workflow_dir = _client(tmp_path, extra_files={"workflow.toml.bak": "x"})
    for bad in ["workflow.toml", "../evil.md", "rules/../../evil.md", "criteria/x.md"]:
        response = client.put(
            "/api/learning/explainer/instructions",
            json={"path": bad, "content": "hacked"},
        )
        assert response.status_code in (400, 404), bad
    # the workflow manifest is untouched
    assert "explainer" in (workflow_dir / "workflow.toml").read_text(encoding="utf-8")


def test_save_rejects_non_markdown_path(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, extra_files={"rules/notes.txt": "x"})
    response = client.put(
        "/api/learning/explainer/instructions",
        json={"path": "rules/notes.txt", "content": "hacked"},
    )
    assert response.status_code in (400, 404)
