import { useCallback, useEffect, useState } from "react";
import { fetchWorkflows, rescanWorkflows } from "../api";
import type { Workflow } from "../types";
import { WorkflowCard } from "./WorkflowCard";

type WorkflowGridProps = {
  onCount: (count: number | null) => void;
  onStarted: (workflowId: string, runId: string) => void;
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function WorkflowGrid({ onCount, onStarted }: WorkflowGridProps) {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [rescanning, setRescanning] = useState(false);

  const applyList = useCallback(
    (list: Workflow[]) => {
      setWorkflows(list);
      setStatus("ready");
      setError(null);
      onCount(list.length);
    },
    [onCount],
  );

  const applyError = useCallback(
    (err: unknown, fallback: string) => {
      setWorkflows([]);
      setStatus("error");
      setError(messageOf(err, fallback));
      onCount(null);
    },
    [onCount],
  );

  useEffect(() => {
    let cancelled = false;
    void fetchWorkflows().then(
      (list) => {
        if (!cancelled) {
          applyList(list);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          applyError(err, "Could not load workflows");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [applyList, applyError]);

  function onRetry() {
    setStatus("loading");
    setError(null);
    onCount(null);
    void fetchWorkflows().then(applyList, (err: unknown) => {
      applyError(err, "Could not load workflows");
    });
  }

  async function onRescan() {
    setRescanning(true);
    try {
      applyList(await rescanWorkflows());
    } catch (err) {
      applyError(err, "Could not rescan workflows");
    } finally {
      setRescanning(false);
    }
  }

  const countNote =
    status === "ready"
      ? `${workflows.length} plug-in${workflows.length === 1 ? "" : "s"} found in `
      : null;

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Workflows</div>
          {countNote ? (
            <div className="page-note">
              {countNote}
              <span className="path">workflows/</span>.
            </div>
          ) : (
            <div className="page-note">
              Plug-ins in <span className="path">workflows/</span>.
            </div>
          )}
        </div>
        <button
          type="button"
          className="btn btn-sm"
          disabled={rescanning}
          onClick={() => {
            void onRescan();
          }}
        >
          <span className="ico">
            <svg
              width="12"
              height="12"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.4"
            >
              <path d="M14 8a6 6 0 1 1-1.8-4.3" />
              <path d="M14 1.6V4.4h-2.8" />
            </svg>
          </span>
          Rescan folder
        </button>
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading workflows…</div>
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

      {status === "ready" && workflows.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">
              No plug-ins in <span className="path">workflows/</span>. An empty grid is a valid
              Stage 1 state.
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" && workflows.length > 0 ? (
        <div className="grid">
          {workflows.map((workflow) => (
            <WorkflowCard
              key={workflow.id}
              workflow={workflow}
              onStarted={(runId) => {
                onStarted(workflow.id, runId);
              }}
            />
          ))}
        </div>
      ) : null}
    </section>
  );
}
