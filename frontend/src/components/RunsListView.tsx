import { useEffect, useState } from "react";
import { fetchRuns } from "../api";
import { statusPillClass } from "../statusPill";
import type { RunSummary, VideoRef, VideoStatus } from "../types";

type RunsListViewProps = {
  workflowId: string;
  onOpenRun: (runId: string) => void;
  onBack: () => void;
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

const VIDEO_STATUS_ORDER: readonly VideoStatus[] = [
  "complete",
  "running",
  "pending",
  "failed",
  "stopped",
];

function videoCountLabel(videos: VideoRef[]): string {
  const n = videos.length;
  const noun = n === 1 ? "video" : "videos";
  if (n === 0) {
    return "0 videos";
  }
  const counts = new Map<VideoStatus, number>();
  for (const video of videos) {
    counts.set(video.status, (counts.get(video.status) ?? 0) + 1);
  }
  if (counts.size === 1) {
    return `${n} ${noun}`;
  }
  const parts: string[] = [];
  for (const status of VIDEO_STATUS_ORDER) {
    const count = counts.get(status);
    if (count) {
      parts.push(`${count} ${status}`);
    }
  }
  return `${n} ${noun} (${parts.join(", ")})`;
}

export function RunsListView({ workflowId, onOpenRun, onBack }: RunsListViewProps) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void fetchRuns(workflowId).then(
      (data) => {
        if (!cancelled) {
          setRuns(data.runs);
          setStatus("ready");
          setError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setRuns([]);
          setStatus("error");
          setError(messageOf(err, "Could not load runs"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [workflowId, reload]);

  function onRetry() {
    setStatus("loading");
    setError(null);
    setReload((n) => n + 1);
  }

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Runs</div>
          <div className="page-note">
            Past runs for <span className="path">{workflowId}</span>.
          </div>
        </div>
        <button type="button" className="btn btn-sm" onClick={onBack}>
          Back
        </button>
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading runs…</div>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">{error}</div>
            <div className="card-foot">
              <button type="button" className="btn btn-sm" onClick={onRetry}>
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && runs.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">No runs yet.</div>
          </div>
        </div>
      ) : null}

      {status === "ready" && runs.length > 0 ? (
        <div className="panel">
          <div className="run-list">
            {runs.map((run) => (
              <button
                key={run.run_id}
                type="button"
                className="run-row"
                onClick={() => {
                  onOpenRun(run.run_id);
                }}
              >
                <div className="run-row-main">
                  <div className="run-row-id path">{run.run_id}</div>
                  <div className="run-row-meta">
                    {run.started_utc} · {videoCountLabel(run.videos)}
                  </div>
                </div>
                <span className={statusPillClass(run.status)}>{run.status}</span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
