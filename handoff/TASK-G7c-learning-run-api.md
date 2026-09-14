# TASK G-7c — learning-run API (run / staged / accept / reject) (§5.11)

## Goal (one sentence)
Wire the learning pieces into the API: start a learning run (stage bounded proposals), read the
staged proposals, and accept or reject them — with the optimiser INJECTED so tests run unpaid.

## Governing spec (verbatim — Architecture §5.11)
> run the SkillOpt-derived optimiser to propose bounded edits. … Proposals are written to a staging
> area and never applied directly. The live files are untouched until the user accepts.
>
> On any error, the staging area is discarded and the learning run returns entirely to its state
> before it began, with nothing modified.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_learning_run_api.py`.

## What to implement (TWO files only)

### 1) `app/main.py` — two new `create_app` kwargs + wiring
Add to `create_app(...)`:
- `learning_staging_dir: Path | None = None` → `application.state.learning_staging_dir =
  learning_staging_dir or (APP_ROOT / "state" / "learning-staging")`. (Import `APP_ROOT` from
  `app.paths`; this default is disjoint from `WORKFLOWS_DIR`.)
- `make_learning_optimizer: MakeLearningOptimizer | None = None` →
  `application.state.make_learning_optimizer = make_learning_optimizer or
  make_default_learning_optimizer(resolved, application.state.budget)` (see the factory below;
  `resolved` is the same secrets mapping already used for `application.state.secrets`).

Do not change any other create_app behaviour. Keep the existing router registrations.

### 2) `app/api/learning.py` — the factory type, default factory, and four endpoints
Add near the top:
```python
from collections.abc import Callable, Mapping
from sfvf.context import BudgetConfig
from app.learning.engine import LearningError, OptimizeFn, ProposedEdit, run_learning
from app.learning.accept import accept_learning, reject_learning
from app.learning.optimizer import make_optimizer
from app.learning.completion import make_openrouter_completion
from app.paths import is_safe_path_segment

LEARNING_MODEL = "openai/gpt-4o-mini"  # conservative default; operator tunes later
type MakeLearningOptimizer = Callable[[str, str], OptimizeFn]  # (workflow_id, run_id) -> OptimizeFn


def make_default_learning_optimizer(
    secrets: Mapping[str, str], budget: BudgetConfig | None
) -> MakeLearningOptimizer:
    def factory(workflow_id: str, run_id: str) -> OptimizeFn:
        return make_optimizer(
            make_openrouter_completion(
                secrets=secrets, budget=budget, model=LEARNING_MODEL, run_id=run_id
            )
        )
    return factory
```

Pydantic response models:
- `class StagedProposalOut(BaseModel): path: str; content: str`
- `class StagedOut(BaseModel): staged: list[StagedProposalOut]`
- `class AcceptOut(BaseModel): applied: list[str]`

Helpers:
- `_entry(request, workflow_id)` → validate `is_safe_path_segment(workflow_id)` (else
  `HTTPException(404)`), `entry = _holder(request).get(workflow_id)`; `None` → 404; return `entry`.
- `_staging_for(request, workflow_id) -> Path` → `request.app.state.learning_staging_dir /
  workflow_id`.
- `_read_staged(staging: Path) -> list[StagedProposalOut]` → for each FILE under `staging.rglob("*")`
  (sorted), path = POSIX relpath to `staging`, content = file text; `[]` when the dir is absent.

Endpoints (router already has `prefix="/api"`):
- `POST /learning/{workflow_id}/run` → `entry = _entry(...)`; `staging = _staging_for(...)`;
  `run_id = f"learning-{workflow_id}-{uuid.uuid4().hex}"`;
  `optimize = request.app.state.make_learning_optimizer(workflow_id, run_id)`; then
  `try: result = run_learning(entry.path, runs_dir=_runs_dir(request), staging_dir=staging,
  optimize=optimize)` `except LearningError: raise HTTPException(status_code=502, detail="learning
  run failed")`. Return `StagedOut(staged=[StagedProposalOut(path=e.path, content=e.content) for e in
  result.staged])`.
- `GET /learning/{workflow_id}/staged` → `_entry(...)`; return `StagedOut(staged=_read_staged(
  _staging_for(...)))`.
- `POST /learning/{workflow_id}/accept` → `entry = _entry(...)`; `result = accept_learning(entry.path,
  _staging_for(...))`; return `AcceptOut(applied=result.applied)`.
- `POST /learning/{workflow_id}/reject` → `_entry(...)`; `reject_learning(_staging_for(...))`; return
  `{"ok": True}` (or a small model).

Keep the existing `GET /learning` list endpoint (G-4) exactly as is.

## Constraints / do-nots
- Touch ONLY `app/main.py` and `app/api/learning.py`. Do NOT edit the test, the SDK, or the learning
  engine/optimizer/completion/accept modules. Reuse their functions; do not reimplement them.
- No real network in the test path — the optimiser is injected via `make_learning_optimizer`; the
  DEFAULT factory (production) is the only place the real OpenRouter call is constructed, and it is
  never invoked by the frozen test.
- Keep `ruff check .`, `ruff format --check .`, and `mypy sdk app` clean; ≤100 cols.

## Scope
- `app/main.py`
- `app/api/learning.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_learning_run_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
