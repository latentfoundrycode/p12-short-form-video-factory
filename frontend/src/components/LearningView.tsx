import { useEffect, useState } from "react";
import { acceptLearning, fetchLearning, rejectLearning, runLearning } from "../api";
import type { LearningRow, StagedProposal } from "../types";

type RunStatus = "idle" | "running" | "ready" | "error";

type WorkflowRun = {
  status: RunStatus;
  proposals: StagedProposal[];
  error: string | null;
};

const idleRun: WorkflowRun = {
  status: "idle",
  proposals: [],
  error: null,
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function LearningView() {
  const [reloadKey, setReloadKey] = useState(0);
  const [workflows, setWorkflows] = useState<LearningRow[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, WorkflowRun>>({});
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchLearning().then(
      (rows) => {
        if (!cancelled) {
          setWorkflows(rows);
          setStatus("ready");
          setError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setWorkflows([]);
          setStatus("error");
          setError(messageOf(err, "Could not load learning data"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  function startLearning(workflow: LearningRow): void {
    const id = workflow.workflow_id;
    setRuns((current) => ({
      ...current,
      [id]: { status: "running", proposals: [], error: null },
    }));

    void runLearning(id).then(
      (proposals) => {
        setRuns((current) => ({
          ...current,
          [id]: { status: "ready", proposals, error: null },
        }));
        if (proposals.length > 0) {
          setReviewError(null);
          setSelectedWorkflowId(id);
        }
      },
      (err: unknown) => {
        setRuns((current) => ({
          ...current,
          [id]: {
            status: "error",
            proposals: [],
            error: messageOf(err, "Could not start learning"),
          },
        }));
      },
    );
  }

  async function acceptSelected(): Promise<void> {
    if (selectedWorkflowId === null) return;

    const id = selectedWorkflowId;
    setReviewSubmitting(true);
    setReviewError(null);
    try {
      await acceptLearning(id);
      setRuns((current) => ({ ...current, [id]: idleRun }));
      setSelectedWorkflowId(null);
      setStatus("loading");
      setError(null);
      setReloadKey((key) => key + 1);
    } catch (err) {
      setReviewError(messageOf(err, "Could not accept learning"));
    } finally {
      setReviewSubmitting(false);
    }
  }

  async function rejectSelected(): Promise<void> {
    if (selectedWorkflowId === null) return;

    const id = selectedWorkflowId;
    setReviewSubmitting(true);
    setReviewError(null);
    try {
      await rejectLearning(id);
      setRuns((current) => ({ ...current, [id]: idleRun }));
      setSelectedWorkflowId(null);
    } catch (err) {
      setReviewError(messageOf(err, "Could not reject learning"));
    } finally {
      setReviewSubmitting(false);
    }
  }

  const selectedWorkflow =
    selectedWorkflowId === null
      ? null
      : (workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId) ?? null);
  const selectedRun = selectedWorkflowId === null ? null : (runs[selectedWorkflowId] ?? idleRun);
  const selectedProposals = selectedRun?.proposals ?? [];

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
        <div className="two">
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
                  const run = runs[workflow.workflow_id] ?? idleRun;
                  const counts = `${workflow.rules_count} rules, ${workflow.skills_count} skills`;
                  const idleDetails =
                    workflow.last_learned === null
                      ? counts
                      : `Last learned ${workflow.last_learned} · ${counts}`;
                  const details =
                    run.status === "running"
                      ? `Reading ${workflow.label_count} labels…`
                      : run.status === "ready"
                        ? run.proposals.length === 0
                          ? "No changes proposed"
                          : `${run.proposals.length} edits proposed, awaiting your review`
                        : run.status === "error"
                          ? run.error
                          : idleDetails;
                  const stateClass =
                    run.status === "running" ? " s-run" : run.status === "ready" ? " s-done" : "";

                  return (
                    <div className={`lrn${stateClass}`} key={workflow.workflow_id}>
                      <div className="lrn-count">
                        {workflow.label_count}
                        <small>labels</small>
                      </div>
                      <div className="li-main">
                        <div className="li-title">{workflow.name || workflow.workflow_id}</div>
                        <div className="li-sub">{details}</div>
                      </div>
                      {run.status === "idle" ? (
                        <button
                          type="button"
                          className="btn btn-sm"
                          disabled={workflow.label_count === 0}
                          onClick={() => {
                            startLearning(workflow);
                          }}
                        >
                          Start learning
                        </button>
                      ) : null}
                      {run.status === "running" ? <span className="pill run">Running</span> : null}
                      {run.status === "ready" && run.proposals.length > 0 ? (
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={reviewSubmitting}
                          onClick={() => {
                            setReviewError(null);
                            setSelectedWorkflowId(workflow.workflow_id);
                          }}
                        >
                          Review
                        </button>
                      ) : null}
                      {run.status === "error" ? (
                        <button
                          type="button"
                          className="btn btn-sm"
                          onClick={() => {
                            setRuns((current) => ({
                              ...current,
                              [workflow.workflow_id]: idleRun,
                            }));
                          }}
                        >
                          Retry
                        </button>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {selectedWorkflow !== null && selectedProposals.length > 0 ? (
            <div className="panel">
              <div className="panel-head">
                <span className="eyebrow">
                  Proposed · {selectedWorkflow.name || selectedWorkflow.workflow_id}
                </span>
                <span className="pill done">{selectedProposals.length} edits</span>
              </div>
              <div className="panel-body">
                {selectedProposals.map((proposal, proposalIndex) => (
                  <div className="diff" key={`${proposal.path}-${proposalIndex}`}>
                    <div className="diff-head">
                      <span>{proposal.path}</span>
                      <span>proposed</span>
                    </div>
                    <div className="diff-body">
                      {proposal.content.split("\n").map((line, lineIndex) => (
                        <div className="dl" key={lineIndex}>
                          <span className="dl-mark"> </span>
                          <span>{line}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
                {reviewError === null ? null : <div className="page-note">{reviewError}</div>}
                <div className="card-foot">
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={reviewSubmitting}
                    onClick={() => void acceptSelected()}
                  >
                    Accept all {selectedProposals.length}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    disabled={reviewSubmitting}
                    onClick={() => void rejectSelected()}
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
