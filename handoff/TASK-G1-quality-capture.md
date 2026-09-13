# TASK G-1 — quality-capture API (§9, §11.1, §5.11)

## Goal (one sentence)
Add `POST /api/workflows/{workflow_id}/runs/{run_id}/quality` that writes the user's worded answers,
accept/reject, and within-request ranking positions into each finished video's `video.json`
(`VideoRecord.quality`), validated against the workflow's declared `quality_factors`.

## Governing spec (verbatim)
§9: "After a Generation Request finishes, the user writes a free-text answer to each factor for every
video, then ranks that request's videos against one another for each factor. Accept or reject is
recorded separately. **There are no numeric ratings.**"
§5.11: the learning process later "gather[s] every `video.json` containing quality answers since the
last learning run" — so answers/rankings/accept must live IN each video.json.

## Frozen contract (already committed — do NOT edit)
`tests/api/test_quality_api.py`. Read it as the source of truth; the notes below explain intent.

## Current state (already present, do NOT rebuild)
- `[[quality_factors]]` are parsed + validated: `app/registry/schema.py::QualityFactor` (`.key`,
  `.question`); a workflow's factors are `entry.manifest.quality_factors` (each `.key`), where
  `entry = request.app.state.registry.get(workflow_id)` (a `WorkflowEntry`; `.manifest` may be None).
- `VideoRecord.quality: dict[str, Any] | None` exists (`app/core/records.py`). Persist via
  read→set→write: `read_video(video_dir)` → `record.model_copy(update={"quality": ...})` →
  `write_video(video_dir, record)`. The video dir is `run_dir / format_video_dir(index, count)`
  (`app/core/layout.py`).
- The run dir is `runs_dir / workflow_id / run_id` (`runs_dir` = `request.app.state.runs_dir`, see
  `app/api/runs.py::_runs_dir`). `read_request(run_dir)` gives the `RequestRecord` (`.status`,
  `.videos` each with `.index`). Terminal statuses: reuse the set in `app/api/runs.py`
  (`_TERMINAL_STATUSES`) — import it or mirror the same frozenset.
- Guard `workflow_id`/`run_id` with `is_safe_path_segment` (from `app.paths`), matching `runs.py`.

## What to implement

### `app/api/quality.py` (new)
`router = APIRouter(prefix="/api")`. Mirror the style of `app/api/runs.py`.

Body models (Pydantic, `ConfigDict(extra="forbid")`):
```python
class VideoQualityIn(BaseModel):
    index: int
    answers: dict[str, str] = Field(default_factory=dict)
    accepted: bool | None = None

class QualitySubmissionIn(BaseModel):
    videos: list[VideoQualityIn] = Field(default_factory=list)
    rankings: dict[str, list[int]] = Field(default_factory=dict)
```

Handler `submit_quality(workflow_id, run_id, body, request)`:
1. `is_safe_path_segment(workflow_id)` and the workflow exists in the registry, else `404`. `run_id`
   safe and `run_dir / "request.json"` exists, else `404`.
2. `read_request(run_dir)`; if `status` not in the terminal set → `409` ("can only record quality for
   a finished request"). (§9: "After a Generation Request finishes".)
3. `declared = {f.key for f in entry.manifest.quality_factors}` (empty set if `entry.manifest` is
   None). `request_indices = {v.index for v in record.videos}`.
4. Validate (any failure → `422` via `HTTPException`, and write NOTHING to any video.json):
   - every `answers` key across all body videos is in `declared`;
   - every key in `rankings` is in `declared`;
   - each body `video.index` is in `request_indices`;
   - each `rankings[factor]` list is a PERMUTATION of `request_indices` — same set, no duplicates,
     complete (so `sorted(list) == sorted(request_indices)`).
   Do all validation BEFORE any write.
5. Write: for each `index` in `request_indices`, build a `quality` dict:
   - `answers`: the matching body video's `answers` if non-empty (omit if none);
   - `accepted`: the matching body video's `accepted` if not None (omit if None);
   - `rankings`: `{factor: position}` for each ranked factor, where `position` is this index's
     1-based position in `rankings[factor]` (i.e. `rankings[factor].index(index) + 1`).
   If the dict is empty for that index, leave its video.json unchanged (do not write, do not set an
   empty quality). Otherwise read→`model_copy(update={"quality": dict})`→write that video.json.
6. Return `200` with `{"videos": [{"index": i, "quality": {...}}, ...]}` listing only the videos that
   were written, in ascending index order.

### `app/main.py`
Import and `application.include_router(quality_router)` alongside the others. Nothing else changes.

## Constraints / do-nots
- Touch ONLY `app/api/quality.py` (new) and `app/main.py`. Do NOT edit any test,
  `app/core/records.py`, the registry, the frontend, or the optimiser (there is none yet).
- No numeric ratings anywhere. No new dependency.
- Keep `ruff check`, `ruff format --check`, and `mypy --strict` (`mypy sdk app`) clean; wrap ≤100 cols.

## Scope
- `app/api/quality.py`
- `app/main.py`

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_quality_api.py -q` → all pass.
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
