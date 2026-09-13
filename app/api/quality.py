from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.runs import _TERMINAL_STATUSES, _holder, _runs_dir
from app.core.layout import format_video_dir
from app.core.records import VideoRecord, read_request, read_video, write_video
from app.paths import is_safe_path_segment

router = APIRouter(prefix="/api")


class VideoQualityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    answers: dict[str, str] = Field(default_factory=dict)
    accepted: bool | None = None


class QualitySubmissionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    videos: list[VideoQualityIn] = Field(default_factory=list)
    rankings: dict[str, list[int]] = Field(default_factory=dict)


@router.post("/workflows/{workflow_id}/runs/{run_id}/quality")
def submit_quality(
    workflow_id: str,
    run_id: str,
    body: QualitySubmissionIn,
    request: Request,
) -> dict[str, list[dict[str, Any]]]:
    if not is_safe_path_segment(workflow_id):
        raise HTTPException(status_code=404)
    entry = _holder(request).get(workflow_id)
    if entry is None:
        raise HTTPException(status_code=404)
    if not is_safe_path_segment(run_id):
        raise HTTPException(status_code=404)
    run_dir = _runs_dir(request) / workflow_id / run_id
    if not (run_dir / "request.json").is_file():
        raise HTTPException(status_code=404)

    record = read_request(run_dir)
    if record.status not in _TERMINAL_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="can only record quality for a finished request",
        )

    declared = set() if entry.manifest is None else {f.key for f in entry.manifest.quality_factors}
    request_indices = {video.index for video in record.videos}

    if any(set(video.answers) - declared for video in body.videos):
        raise HTTPException(status_code=422, detail="answers contain an unknown quality factor")
    if set(body.rankings) - declared:
        raise HTTPException(status_code=422, detail="rankings contain an unknown quality factor")
    if any(video.index not in request_indices for video in body.videos):
        raise HTTPException(status_code=422, detail="video index is not part of the request")
    if any(sorted(ranking) != sorted(request_indices) for ranking in body.rankings.values()):
        raise HTTPException(
            status_code=422,
            detail="ranking must contain every request video index exactly once",
        )

    body_videos = {video.index: video for video in body.videos}
    pending: list[tuple[Path, VideoRecord, dict[str, Any], int]] = []
    for index in sorted(request_indices):
        quality: dict[str, Any] = {}
        submitted = body_videos.get(index)
        if submitted is not None:
            if submitted.answers:
                quality["answers"] = submitted.answers
            if submitted.accepted is not None:
                quality["accepted"] = submitted.accepted
        if body.rankings:
            quality["rankings"] = {
                factor: ranking.index(index) + 1 for factor, ranking in body.rankings.items()
            }
        if not quality:
            continue

        video_dir = run_dir / format_video_dir(index, len(record.videos))
        if not (video_dir / "video.json").is_file():
            continue
        pending.append(
            (
                video_dir,
                read_video(video_dir).model_copy(update={"quality": quality}),
                quality,
                index,
            )
        )

    written = [
        {"index": index, "quality": quality} for _video_dir, _record_out, quality, index in pending
    ]
    for video_dir, record_out, _quality, _index in pending:
        write_video(video_dir, record_out)

    return {"videos": written}
