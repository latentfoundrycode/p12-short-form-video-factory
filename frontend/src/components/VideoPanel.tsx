import { runFileUrl, runVideoDirectory } from "../api";
import type { RunFile, VideoRecord } from "../types";

type VideoPanelProps = {
  workflowId: string;
  runId: string;
  videos: VideoRecord[];
  files: RunFile[];
};

function pillClass(status: VideoRecord["status"]): string {
  switch (status) {
    case "complete":
      return "done";
    case "failed":
      return "fail";
    case "stopped":
      return "warn";
    case "running":
      return "run";
    case "pending":
      return "idle";
  }
}

function selfReviewFailure(selfReview: Record<string, unknown> | null | undefined): string | null {
  if (!selfReview || typeof selfReview !== "object") return null;
  if (selfReview.passed !== false) return null;

  const failures = Array.isArray(selfReview.failures)
    ? selfReview.failures.filter((failure): failure is string => typeof failure === "string")
    : [];

  return failures.length > 0
    ? `Self-review failed: ${failures.join(", ")}`
    : "Self-review did not pass.";
}

export function VideoPanel({ workflowId, runId, videos, files }: VideoPanelProps) {
  const sortedVideos = [...videos].sort((a, b) => a.index - b.index);

  return (
    <div className="panel">
      <div className="panel-head">
        <span className="eyebrow">Video</span>
      </div>
      <div className="panel-body stack">
        {sortedVideos.length === 0 ? (
          <div className="page-note">No video records.</div>
        ) : (
          sortedVideos.map((video) => {
            const videoDir = runVideoDirectory(video.index);
            const finalPath = `${videoDir}/final.mp4`;
            const reviewFailure = selfReviewFailure(video.self_review);
            const file =
              files.find((item) => item.path === finalPath) ??
              files.find(
                (item) =>
                  item.path.startsWith(`${videoDir}/`) && item.path.toLowerCase().endsWith(".mp4"),
              );

            return (
              <div className="field" key={video.index}>
                <div className="video-head">
                  <div className="eyebrow">#{video.index}</div>
                  <span className={`pill ${pillClass(video.status)}`}>{video.status}</span>
                </div>
                {reviewFailure ? (
                  <div className="page-note video-review-fail">{reviewFailure}</div>
                ) : null}
                {file ? (
                  <video
                    aria-label={`Video #${video.index}`}
                    className="run-video"
                    controls
                    preload="metadata"
                    src={runFileUrl(workflowId, runId, file.path)}
                  />
                ) : (
                  <div className="page-note">No video file for #{video.index}</div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
