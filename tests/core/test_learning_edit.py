"""#3 contract: apply a single manual instruction-file edit (Architecture §5.11).

§5.11: "**Acceptance archives the previous version. The prior file moves to `archive/` and the
version number in its frontmatter increments**, so the record of which instructions produced which
past video stays accurate."

The in-app rules/skills editor lets the user edit one `rules/` or `skills/` file by hand and save
it. A manual save must go through the SAME archive-and-version-bump path acceptance uses, so the
provenance record stays accurate whether an edit came from the optimiser or from the user's own
keyboard. `apply_instruction_edit(workflow_dir, relative_path, content)` archives the current live
file (if any) keyed by its version, writes the new content to the live path with its frontmatter
`version` set to prior+1 (a brand-new file starts at version 1), and returns the new version. Only
paths under `rules/` or `skills/` are permitted; anything else raises `AcceptError`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.learning.accept import AcceptError, apply_instruction_edit


def _live(workflow_dir: Path, rel: str, text: str) -> None:
    path = workflow_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_apply_edit_archives_prior_and_bumps_version(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 3\n---\nBe concrete.")

    new_version = apply_instruction_edit(
        workflow_dir, "rules/tone.md", "---\nversion: 3\n---\nOpen on an object."
    )

    assert new_version == 4
    live = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "Open on an object." in live  # the edited content is now live
    assert "version: 4" in live  # frontmatter version incremented (3 -> 4)
    assert "version: 4---" not in live  # closing fence not glued to the version line
    # the prior version is archived under archive/, keyed by its old version number
    archived = list((workflow_dir / "archive").rglob("*.md"))
    assert len(archived) == 1
    assert "Be concrete." in archived[0].read_text(encoding="utf-8")
    assert "v3" in archived[0].name


def test_apply_edit_new_file_starts_at_version_1(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    new_version = apply_instruction_edit(
        workflow_dir, "skills/composition.md", "# Composition\nUse the safe zone."
    )
    assert new_version == 1
    live = (workflow_dir / "skills" / "composition.md").read_text(encoding="utf-8")
    assert "Use the safe zone." in live
    assert "version: 1" in live  # a brand-new instruction file starts at version 1
    assert not (workflow_dir / "archive").exists()  # nothing to archive


def test_apply_edit_normalizes_crlf_line_endings(tmp_path: Path) -> None:
    # The manual editor's content arrives from a browser textarea and on Windows carries CRLF.
    # `_set_version`'s frontmatter regex is LF-only, so without normalization a CRLF body gets a
    # SECOND frontmatter block prepended, leaving a stale version line in the saved file. The saved
    # file must have exactly one frontmatter block, LF endings, and the bumped version only.
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 2\n---\nBe concrete.")
    new_version = apply_instruction_edit(
        workflow_dir, "rules/tone.md", "---\r\nversion: 2\r\n---\r\nOpen on an object.\r\n"
    )
    assert new_version == 3
    live = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "\r" not in live  # line endings normalized to LF
    assert live.count("---") == 2  # exactly one frontmatter block (open + close), not duplicated
    assert "version: 3" in live
    assert "version: 2" not in live  # no stale version line left behind in the body
    assert "Open on an object." in live


def test_apply_edit_rejects_path_outside_rules_and_skills(tmp_path: Path) -> None:
    # Defence in depth: a manual edit must never touch a path outside rules/ or skills/.
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    _live(workflow_dir, "workflow.toml", "id = 'explainer'")
    with pytest.raises(AcceptError):
        apply_instruction_edit(workflow_dir, "workflow.toml", "id = 'hacked'")
    assert "explainer" in (workflow_dir / "workflow.toml").read_text(encoding="utf-8")  # untouched


def test_apply_edit_rejects_traversal_and_absolute_paths(tmp_path: Path) -> None:
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    for bad in ["rules/../../evil.md", "rules\\..\\evil.md", "/etc/passwd", "rules"]:
        with pytest.raises(AcceptError):
            apply_instruction_edit(workflow_dir, bad, "x")
