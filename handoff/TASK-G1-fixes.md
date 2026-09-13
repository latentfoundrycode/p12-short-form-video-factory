# TASK G-1 fixes — don't 500 when a request video has no video.json

## Why
Both reviewers (diff-reviewer + security-auditor) converged: the write loop in
`app/api/quality.py::submit_quality` calls `read_video` unconditionally for every request video
index. A terminal-but-incomplete request (status `partial`/`stopped`/`failed`) can have a video that
never produced a `video.json` (it failed or stayed pending). `read_video` then raises
`FileNotFoundError` mid-loop → unhandled 500, and any earlier index was already written (partial
commit). A committed locking test
(`tests/api/test_quality_api.py::test_missing_video_json_is_skipped_not_500`) is RED.

## Scope
- `app/api/quality.py`

## Exact change (in `submit_quality`, the write loop only — change nothing else)
Make the loop (a) skip an index whose `video.json` does not exist (mirroring
`app/api/runs.py::_detail`, which guards with `if (folder / "video.json").is_file()`), and (b)
collect all updates first, then write, so a video with no record is simply not written (no partial
commit, no 500). Replace the current write loop body so that, for each `index` in
`sorted(request_indices)`:
- build the `quality` dict exactly as now (answers/accepted/rankings; `continue` if empty);
- compute `video_dir = run_dir / format_video_dir(index, len(record.videos))`;
- if `not (video_dir / "video.json").is_file()`: `continue` (skip — the video produced no record);
- otherwise append `(video_dir, read_video(video_dir).model_copy(update={"quality": quality}), quality, index)`
  to a pending list.
Then, after the loop, write every pending entry (`write_video(video_dir, record)`) and build the
`written` response list (`{"index": index, "quality": quality}`) in ascending index order.

Equivalent shape:
```python
pending: list[tuple[Path, VideoRecord, dict[str, Any], int]] = []
for index in sorted(request_indices):
    quality = ...  # unchanged construction
    if not quality:
        continue
    video_dir = run_dir / format_video_dir(index, len(record.videos))
    if not (video_dir / "video.json").is_file():
        continue
    pending.append((video_dir, read_video(video_dir).model_copy(update={"quality": quality}), quality, index))
written = [
    {"index": index, "quality": quality}
    for video_dir, record_out, quality, index in pending
]
for video_dir, record_out, _quality, _index in pending:
    write_video(video_dir, record_out)
return {"videos": written}
```
Add `from pathlib import Path` and `from app.core.records import VideoRecord` to the imports if not
already present (needed for the type hints above; if you avoid the annotations you may skip them).
Do NOT change the validation block, the 404/409 handling, or the ranking-position maths.

## Verify (from the worktree, `./.venv/Scripts/python.exe`)
- `-m pytest tests/api/test_quality_api.py -q` → all pass (incl. `test_missing_video_json_is_skipped_not_500`).
- `-m pytest -q` (full) → green.
- `-m ruff check .`, `-m ruff format --check .`, `-m mypy sdk app` → clean.
