import { useEffect, useState } from "react";
import { clearFailedRuns, deleteRun, fetchRuns } from "../api";
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

const DISPOSABLE = new Set<RunSummary["status"]>(["failed", "stopped", "stopped-budget"]);

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
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const failedCount = runs.filter((run) => DISPOSABLE.has(run.status)).length;

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

  async function onClearFailed() {
    setClearing(true);
    try {
      await clearFailedRuns(workflowId);
      setConfirmDeleteId(null);
      setConfirmClear(false);
      setActionError(null);
      setReload((n) => n + 1);
    } catch (err: unknown) {
      setActionError(messageOf(err, "Could not clear failed runs"));
    } finally {
      setClearing(false);
    }
  }

  async function onDeleteRun(runId: string) {
    setDeletingId(runId);
    try {
      await deleteRun(workflowId, runId);
      setConfirmDeleteId(null);
      setConfirmClear(false);
      setActionError(null);
      setReload((n) => n + 1);
    } catch (err: unknown) {
      setActionError(messageOf(err, "Could not delete run"));
    } finally {
      setDeletingId(null);
    }
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
        <div className="page-head-actions">
          {confirmClear ? (
            <div className="clear-runs-confirm">
              <span className="page-note">
                Delete {failedCount} failed/stopped runs? This can&apos;t be undone.
              </span>
              <button
                type="button"
                className="btn btn-sm btn-danger"
                autoFocus
                disabled={clearing}
                onClick={() => {
                  void onClearFailed();
                }}
              >
                Clear
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  setConfirmClear(false);
                }}
              >
                Cancel
              </button>
            </div>
          ) : failedCount > 0 ? (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setConfirmDeleteId(null);
                setConfirmClear(true);
                setActionError(null);
              }}
            >
              Clear failed ({failedCount})
            </button>
          ) : null}
          <button type="button" className="btn btn-sm" onClick={onBack}>
            Back
          </button>
        </div>
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
          {actionError ? <div className="form-error run-list-error">{actionError}</div> : null}
          <div className="run-list">
            {runs.map((run) => (
              <div key={run.run_id} className="run-row">
                <button
                  type="button"
                  className="run-row-main"
                  onClick={() => {
                    onOpenRun(run.run_id);
                  }}
                >
                  <div className="run-row-id path">{run.run_id}</div>
                  <div className="run-row-meta">
                    {run.started_utc} · {videoCountLabel(run.videos)}
                  </div>
                </button>
                <div className="run-row-actions">
                  <span className={statusPillClass(run.status)}>{run.status}</span>
                  {confirmDeleteId === run.run_id ? (
                    <>
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        autoFocus
                        disabled={deletingId === run.run_id}
                        onClick={() => {
                          void onDeleteRun(run.run_id);
                        }}
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-ghost"
                        onClick={() => {
                          setConfirmDeleteId(null);
                        }}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        setConfirmDeleteId(run.run_id);
                        setConfirmClear(false);
                        setActionError(null);
                      }}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
