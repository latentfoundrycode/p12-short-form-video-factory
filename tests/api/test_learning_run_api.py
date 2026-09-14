"""G-7c contract: the learning-run API — start, staged, accept, reject (Architecture §5.11).

§5.11: "run the SkillOpt-derived optimiser to propose bounded edits. … Proposals are written to a
staging area and never applied directly. The live files are untouched until the user accepts." and
"On any error, the staging area is discarded and the learning run returns entirely to its state
before it began."

This wires the pieces built earlier into the API. The optimiser is INJECTED via
`create_app(make_learning_optimizer=...)`, so tests run with a stub `OptimizeFn` — NO OpenRouter
call, NO spend. The default (production) factory builds
`make_optimizer(make_openrouter_completion(...))` over the SEPARATE `learning` budget meter; the
first REAL run is the attended money-gate handled elsewhere.

Endpoints (all under /api):
  * POST /learning/{id}/run   → run_learning(workflow_dir, runs_dir, staging_dir, optimize) into a
    per-workflow staging dir under the injected `learning_staging_dir` (disjoint from workflows/);
    returns the staged proposals. A LearningError → 502 (nothing applied).
  * GET  /learning/{id}/staged → the currently staged proposals ([] when none).
  * POST /learning/{id}/accept → accept_learning(workflow_dir, staging_dir); returns applied paths.
  * POST /learning/{id}/reject → reject_learning(staging_dir); live untouched.
Unknown / unsafe workflow id → 404.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.learning.engine import LearningInput, OptimizeFn, ProposedEdit
from app.main import create_app
from tests.registry.fixtures import minimal_toml, write_plugin

_NEW_TONE = "---\nversion: 3\n---\nOpen on a moving object."


def _stub_factory(edits: list[ProposedEdit]) -> object:
    """A make_learning_optimizer(workflow_id, run_id) -> OptimizeFn that ignores its input."""

    def factory(workflow_id: str, run_id: str) -> OptimizeFn:
        def optimize(_learning_input: LearningInput) -> list[ProposedEdit]:
            return list(edits)

        return optimize

    return factory


def _setup(
    tmp_path: Path,
    *,
    edits: list[ProposedEdit] | None = None,
    factory: object | None = None,
) -> tuple[TestClient, Path, Path]:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    write_plugin(
        workflows,
        "explainer",
        minimal_toml("explainer"),
        extra_files={
            "rules/tone.md": "---\nversion: 3\n---\nBe concrete.",
            "skills/hooks.md": "# Hooks\nOpen on motion.",
            "criteria/criteria.md": "Earn the first three seconds.",
        },
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    staging = tmp_path / "learning-staging"
    if factory is None:
        factory = _stub_factory(
            edits if edits is not None else [ProposedEdit("rules/tone.md", _NEW_TONE)]
        )
    app = create_app(
        workflows_dir=workflows,
        runs_dir=runs,
        learning_staging_dir=staging,
        learning_state_dir=tmp_path / "learning-state",
        make_learning_optimizer=factory,
    )
    return TestClient(app), workflows / "explainer", staging


def test_run_stages_proposals_and_returns_them(tmp_path: Path) -> None:
    client, workflow_dir, staging = _setup(tmp_path)
    resp = client.post("/api/learning/explainer/run")
    assert resp.status_code == 200
    staged = resp.json()["staged"]
    assert [p["path"] for p in staged] == ["rules/tone.md"]
    assert "Open on a moving object." in staged[0]["content"]
    # written to the staging area, NOT to the live workflow
    assert (staging / "explainer" / "rules" / "tone.md").is_file()
    assert (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8").endswith("Be concrete.")


def test_staged_endpoint_reads_back_the_proposals(tmp_path: Path) -> None:
    client, _workflow_dir, _staging = _setup(tmp_path)
    assert client.get("/api/learning/explainer/staged").json()["staged"] == []
    client.post("/api/learning/explainer/run")
    staged = client.get("/api/learning/explainer/staged").json()["staged"]
    assert [p["path"] for p in staged] == ["rules/tone.md"]


def test_accept_applies_to_live_and_bumps_version(tmp_path: Path) -> None:
    client, workflow_dir, staging = _setup(tmp_path)
    client.post("/api/learning/explainer/run")
    resp = client.post("/api/learning/explainer/accept")
    assert resp.status_code == 200
    assert "rules/tone.md" in resp.json()["applied"]
    live = (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8")
    assert "Open on a moving object." in live
    assert "version: 4" in live  # §5.11: acceptance bumps the frontmatter version (3 -> 4)
    archived = list((workflow_dir / "archive").rglob("*.md"))
    assert len(archived) == 1 and "Be concrete." in archived[0].read_text(encoding="utf-8")
    # staging consumed on accept
    assert not any((staging / "explainer").rglob("*")) if (staging / "explainer").exists() else True


def test_reject_discards_staging_and_leaves_live_untouched(tmp_path: Path) -> None:
    client, workflow_dir, staging = _setup(tmp_path)
    client.post("/api/learning/explainer/run")
    assert client.post("/api/learning/explainer/reject").status_code == 200
    assert (workflow_dir / "rules" / "tone.md").read_text(encoding="utf-8").endswith("Be concrete.")
    assert not (workflow_dir / "archive").exists()
    assert client.get("/api/learning/explainer/staged").json()["staged"] == []


def test_run_maps_learning_error_to_502_and_applies_nothing(tmp_path: Path) -> None:
    # An optimiser that proposes a path outside rules/skills makes run_learning raise LearningError;
    # the API surfaces 502 and the live workflow is untouched.
    client, workflow_dir, _staging = _setup(
        tmp_path, edits=[ProposedEdit("criteria/criteria.md", "hacked")]
    )
    assert client.post("/api/learning/explainer/run").status_code == 502
    assert (workflow_dir / "criteria" / "criteria.md").read_text(
        encoding="utf-8"
    ) == "Earn the first three seconds."


def test_unknown_workflow_is_404(tmp_path: Path) -> None:
    client, _workflow_dir, _staging = _setup(tmp_path)
    assert client.post("/api/learning/ghost/run").status_code == 404
    assert client.get("/api/learning/ghost/staged").status_code == 404
    assert client.post("/api/learning/../etc/run").status_code == 404
