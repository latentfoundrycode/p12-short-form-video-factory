import { useEffect, useState } from "react";
import { fetchLearning } from "../api";
import type { LearningRow } from "../types";

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : "Could not load learning data";
}

export function LearningView() {
  const [reloadKey, setReloadKey] = useState(0);
  const [workflows, setWorkflows] = useState<LearningRow[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchLearning().then(
      (rows) => {
        if (!cancelled) {
          setWorkflows(rows);
          setStatus("ready");
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setWorkflows([]);
          setStatus("error");
          setError(messageOf(err));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Learning</div>
          <div className="page-note">
            Proposes edits to a workflow&apos;s own rules and skills from your answers and rankings.
            Global instructions are never touched.
          </div>
        </div>
      </div>

      {status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading learning data…</div>
          </div>
        </div>
      ) : null}

      {status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">{error}</div>
            <div className="card-foot">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  setStatus("loading");
                  setError(null);
                  setReloadKey((key) => key + 1);
                }}
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {status === "ready" ? (
        <div className="panel">
          <div className="panel-head">
            <span className="eyebrow">Workflows</span>
          </div>
          {workflows.length === 0 ? (
            <div className="panel-body">
              <div className="page-note">No workflows yet.</div>
            </div>
          ) : (
            <div className="list">
              {workflows.map((workflow) => {
                const counts = `${workflow.rules_count} rules, ${workflow.skills_count} skills`;
                const details =
                  workflow.last_learned === null
                    ? counts
                    : `Last learned ${workflow.last_learned} · ${counts}`;
                return (
                  <div className="lrn" key={workflow.workflow_id}>
                    <div className="lrn-count">
                      {workflow.label_count}
                      <small>labels</small>
                    </div>
                    <div className="li-main">
                      <div className="li-title">{workflow.name || workflow.workflow_id}</div>
                      <div className="li-sub">{details}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
