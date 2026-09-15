import { runFileUrl, runVideoDirectory } from "../api";
import type { RunFile, VideoRecord } from "../types";

type VideoPanelProps = {
  workflowId: string;
  runId: string;
  videos: VideoRecord[];
  files: RunFile[];
};

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
            const file =
              files.find((item) => item.path === finalPath) ??
              files.find(
                (item) =>
                  item.path.startsWith(`${videoDir}/`) &&
                  item.path.toLowerCase().endsWith(".mp4"),
              );

            return (
              <div className="field" key={video.index}>
                <div className="eyebrow">#{video.index}</div>
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
