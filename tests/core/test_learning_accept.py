"""G-6 contract: accept / reject staged learning proposals (Architecture §5.11).

§5.11: "Proposals are written to a staging area and never applied directly. The live files are
untouched until the user accepts. **Acceptance archives the previous version. The prior file moves
to `archive/` and the version number in its frontmatter increments**, so the record of which
instructions produced which past video stays accurate."

`accept_learning(workflow_dir, staging_dir)` applies every staged file (produced by the G-5 engine,
so each is under `rules/` or `skills/`) to the LIVE workflow: the prior live file moves into
`workflow_dir/archive/` keyed by its version, the staged content is written to the live path with
its frontmatter `version` set to prior+1 (a brand-new file starts at version 1), and the staging
area is then discarded. `reject_learning(staging_dir)` discards staging and changes nothing. The
learning module is the sanctioned exception to "never write into workflows/ while running" — and
even then only rules/skills (+ archive/) are ever written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.learning.accept import AcceptError, accept_learning, reject_learning


def _live(workflow_dir: Path, rel: str, text: str) -> None:
    path = workflow_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _stage(staging_dir: Path, rel: str, text: str) -> None:
    path = staging_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    return workflow_dir, tmp_path / "staging"


def test_accept_archives_prior_and_bumps_version(tmp_path: Path) -> None:
    workflow_dir, staging = _setup(tmp_path)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 3\n---\nBe concrete.")
    _stage(staging, "rules/tone.md", "---\nversion: 3\n---\nOpen on an object.")

    result = accept_learning(workflow_dir, staging)

    live = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "Open on an object." in live  # the accepted content is now live
    assert "version: 4" in live  # frontmatter version incremented (3 -> 4)
    # the prior version is archived under archive/, keyed by its old version number
    archived = list((workflow_dir / "archive").rglob("*.md"))
    assert len(archived) == 1
    assert "Be concrete." in archived[0].read_text(encoding="utf-8")
    assert "v3" in archived[0].name or "3" in archived[0].name
    assert "rules/tone.md" in result.applied
    assert not staging.exists() or not any(staging.rglob("*"))  # staging discarded on accept


def test_accept_new_file_starts_at_version_1(tmp_path: Path) -> None:
    workflow_dir, staging = _setup(tmp_path)
    _stage(staging, "skills/composition.md", "# Composition\nUse the safe zone.")
    accept_learning(workflow_dir, staging)
    live = (workflow_dir / "skills" / "composition.md").read_text(encoding="utf-8")
    assert "Use the safe zone." in live
    assert "version: 1" in live  # a brand-new instruction file starts at version 1
    assert not (workflow_dir / "archive").exists() or not any(
        (workflow_dir / "archive").rglob("*.md")
    )  # nothing to archive


def test_accept_defaults_missing_version_to_one_then_bumps(tmp_path: Path) -> None:
    workflow_dir, staging = _setup(tmp_path)
    _live(
        workflow_dir, "rules/hooks.md", "---\nagents: [hook-writer]\n---\nOld."
    )  # no version line
    _stage(staging, "rules/hooks.md", "---\nagents: [hook-writer]\n---\nNew rule.")
    accept_learning(workflow_dir, staging)
    live = (workflow_dir / "rules" / "hooks.md").read_text(encoding="utf-8")
    assert "New rule." in live
    assert "version: 2" in live  # absent version treated as 1, bumped to 2


def test_reject_discards_staging_and_leaves_live_untouched(tmp_path: Path) -> None:
    workflow_dir, staging = _setup(tmp_path)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 1\n---\nBe concrete.")
    _stage(staging, "rules/tone.md", "---\nversion: 1\n---\nDifferent.")
    reject_learning(staging)
    assert "Be concrete." in (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert not staging.exists() or not any(staging.rglob("*"))
    assert not (workflow_dir / "archive").exists()


def test_accept_refuses_staged_path_outside_rules_and_skills(tmp_path: Path) -> None:
    # Defence in depth: even a staged file outside rules/ or skills/ must not be applied to live.
    workflow_dir, staging = _setup(tmp_path)
    _live(workflow_dir, "workflow.toml", "id = 'explainer'")
    _stage(staging, "workflow.toml", "id = 'hacked'")
    with pytest.raises(AcceptError):
        accept_learning(workflow_dir, staging)
    assert "explainer" in (workflow_dir / "workflow.toml").read_text(encoding="utf-8")  # untouched


def test_accepted_frontmatter_stays_valid_across_reaccept(tmp_path: Path) -> None:
    # §5.11: the frontmatter version must actually increment AND stay a well-formed block,
    # so a later accept reads the true prior version (not a corrupted default). A single
    # substring check hides a version line that swallowed its closing fence ("version: 4---").
    workflow_dir, staging = _setup(tmp_path)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 3\n---\nBe concrete.")
    _stage(staging, "rules/tone.md", "---\nversion: 3\n---\nFirst edit.")
    accept_learning(workflow_dir, staging)

    first = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert first.startswith("---\n")
    assert "\n---\n" in first  # closing fence survives on its own line
    assert "version: 4" in first
    assert "version: 4---" not in first  # fence not glued to the version line

    # a second accept must see prior version 4 -> bump to 5 and archive the prior as v4 (not v1)
    staging2 = tmp_path / "staging2"
    _stage(staging2, "rules/tone.md", "---\nversion: 4\n---\nSecond edit.")
    accept_learning(workflow_dir, staging2)
    second = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "version: 5" in second
    archived = {p.name for p in (workflow_dir / "archive").rglob("*.md")}
    assert any("v3" in name for name in archived)
    assert any("v4" in name for name in archived)  # prior read as 4, not a corrupted 1


def test_refuses_staging_equal_to_workflow_without_data_loss(tmp_path: Path) -> None:
    # Data-loss guard: if staging and the workflow are the same tree (or one contains the
    # other), discarding staging on accept would delete the live workflow. All staged paths
    # are individually valid here, so only an explicit disjointness check catches it — and it
    # must fire BEFORE anything is moved or written.
    workflow_dir = tmp_path / "workflows" / "explainer"
    workflow_dir.mkdir(parents=True)
    _live(workflow_dir, "rules/tone.md", "---\nversion: 1\n---\nBe concrete.")
    with pytest.raises(AcceptError):
        accept_learning(workflow_dir, workflow_dir)
    live = workflow_dir / "rules" / "tone.md"
    assert live.is_file()
    assert live.read_text(encoding="utf-8").endswith("Be concrete.")  # untouched
    assert not (workflow_dir / "archive").exists()  # nothing moved before the refusal
