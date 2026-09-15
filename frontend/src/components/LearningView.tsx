import { Fragment, useEffect, useRef, useState } from "react";
import {
  acceptLearning,
  fetchInstructions,
  fetchLearning,
  rejectLearning,
  runLearning,
  saveInstruction,
} from "../api";
import type { InstructionFile, LearningRow, StagedProposal } from "../types";

type RunStatus = "idle" | "running" | "ready" | "error";
type InstructionStatus = "idle" | "loading" | "ready" | "error";

type WorkflowRun = {
  status: RunStatus;
  proposals: StagedProposal[];
  error: string | null;
};

type WorkflowInstructions = {
  status: InstructionStatus;
  files: InstructionFile[];
  error: string | null;
};

type SelectedFile = {
  workflowId: string;
  path: string;
};

const idleRun: WorkflowRun = {
  status: "idle",
  proposals: [],
  error: null,
};

const idleInstructions: WorkflowInstructions = {
  status: "idle",
  files: [],
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
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filesByWorkflow, setFilesByWorkflow] = useState<Record<string, WorkflowInstructions>>({});
  const [selectedFile, setSelectedFile] = useState<SelectedFile | null>(null);
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
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

  function toggleWorkflow(id: string): void {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }

    setExpandedId(id);
    const current = filesByWorkflow[id];
    if (current?.status === "ready" || current?.status === "loading") {
      return;
    }

    setFilesByWorkflow((entries) => ({
      ...entries,
      [id]: { status: "loading", files: [], error: null },
    }));
    void fetchInstructions(id).then(
      (files) => {
        setFilesByWorkflow((entries) => ({
          ...entries,
          [id]: { status: "ready", files, error: null },
        }));
      },
      (err: unknown) => {
        setFilesByWorkflow((entries) => ({
          ...entries,
          [id]: {
            status: "error",
            files: [],
            error: messageOf(err, "Could not load instruction files"),
          },
        }));
      },
    );
  }

  function selectInstruction(workflowId: string, path: string): void {
    setSelectedFile({ workflowId, path });
    editingRef.current = false;
    setEditing(false);
    setDraft("");
    setSaveError(null);
    setSavedVersion(null);
    setReviewError(null);
    setSelectedWorkflowId(null);
  }

  function startLearning(workflow: LearningRow): void {
    const id = workflow.workflow_id;
    setSelectedFile(null);
    editingRef.current = false;
    setEditing(false);
    setSaveError(null);
    setSavedVersion(null);
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
        if (proposals.length > 0 && !editingRef.current) {
          setSelectedFile(null);
          editingRef.current = false;
          setEditing(false);
          setSaveError(null);
          setSavedVersion(null);
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
      setFilesByWorkflow((entries) => {
        const next = { ...entries };
        delete next[id];
        return next;
      });
      if (selectedFile?.workflowId === id) {
        setSelectedFile(null);
        editingRef.current = false;
        setEditing(false);
        setDraft("");
        setSavedVersion(null);
      }
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

  async function saveSelectedInstruction(): Promise<void> {
    if (selectedFile === null) return;

    const { workflowId, path } = selectedFile;
    const savedContent = draft;
    setSaving(true);
    setSaveError(null);
    setSavedVersion(null);
    try {
      const version = await saveInstruction(workflowId, path, savedContent);
      setFilesByWorkflow((entries) => {
        const workflowFiles = entries[workflowId];
        if (workflowFiles === undefined) return entries;
        return {
          ...entries,
          [workflowId]: {
            ...workflowFiles,
            files: workflowFiles.files.map((file) =>
              file.path === path ? { ...file, content: savedContent } : file,
            ),
          },
        };
      });
      editingRef.current = false;
      setEditing(false);
      setSavedVersion(version);
    } catch (err) {
      setSaveError(messageOf(err, "Could not save instruction file"));
    } finally {
      setSaving(false);
    }
  }

  const selectedWorkflow =
    selectedWorkflowId === null
      ? null
      : (workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId) ?? null);
  const selectedRun = selectedWorkflowId === null ? null : (runs[selectedWorkflowId] ?? idleRun);
  const selectedProposals = selectedRun?.proposals ?? [];
  const selectedInstruction =
    selectedFile === null
      ? null
      : (filesByWorkflow[selectedFile.workflowId]?.files.find(
          (file) => file.path === selectedFile.path,
        ) ?? null);

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
                  const instructions = filesByWorkflow[workflow.workflow_id] ?? idleInstructions;
                  const expanded = expandedId === workflow.workflow_id;
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
                    <Fragment key={workflow.workflow_id}>
                      <div className={`lrn${stateClass}`}>
                        <div className="lrn-count">
                          {workflow.label_count}
                          <small>labels</small>
                        </div>
                        <button
                          type="button"
                          className="li-main"
                          aria-expanded={expanded}
                          onClick={() => toggleWorkflow(workflow.workflow_id)}
                        >
                          <span className="li-title" style={{ display: "block" }}>
                            <span aria-hidden="true">{expanded ? "▾" : "▸"} </span>
                            {workflow.name || workflow.workflow_id}
                          </span>
                          <span className="li-sub" style={{ display: "block" }}>
                            {details}
                          </span>
                        </button>
                        {run.status === "idle" ? (
                          <button
                            type="button"
                            className="btn btn-sm"
                            disabled={workflow.label_count === 0 || saving}
                            onClick={() => {
                              startLearning(workflow);
                            }}
                          >
                            Start learning
                          </button>
                        ) : null}
                        {run.status === "running" ? (
                          <span className="pill run">Running</span>
                        ) : null}
                        {run.status === "ready" && run.proposals.length > 0 ? (
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            disabled={reviewSubmitting || saving}
                            onClick={() => {
                              setSelectedFile(null);
                              editingRef.current = false;
                              setEditing(false);
                              setSaveError(null);
                              setSavedVersion(null);
                              setReviewError(null);
                              setSelectedWorkflowId(workflow.workflow_id);
                            }}
                          >
                            Review
                          </button>
                        ) : null}
                        {run.status === "ready" && run.proposals.length === 0 ? (
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
                            Dismiss
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
                      {expanded ? (
                        <div className="learning-files">
                          {instructions.status === "idle" || instructions.status === "loading" ? (
                            <div className="page-note">Loading instruction files…</div>
                          ) : null}
                          {instructions.status === "error" ? (
                            <div className="form-error">{instructions.error}</div>
                          ) : null}
                          {instructions.status === "ready" && instructions.files.length === 0 ? (
                            <div className="page-note">No rule or skill files yet.</div>
                          ) : null}
                          {instructions.status === "ready"
                            ? instructions.files.map((file) => {
                                const fileSelected =
                                  selectedFile?.workflowId === workflow.workflow_id &&
                                  selectedFile.path === file.path;
                                return (
                                  <button
                                    type="button"
                                    className={`btn btn-sm ${
                                      fileSelected ? "btn-primary" : "btn-ghost"
                                    }`}
                                    aria-pressed={fileSelected}
                                    disabled={saving}
                                    key={file.path}
                                    onClick={() =>
                                      selectInstruction(workflow.workflow_id, file.path)
                                    }
                                  >
                                    {file.path}
                                  </button>
                                );
                              })
                            : null}
                        </div>
                      ) : null}
                    </Fragment>
                  );
                })}
              </div>
            )}
          </div>

          {selectedFile !== null && selectedWorkflowId === null ? (
            <div className="panel">
              <div className="panel-head">
                <span className="eyebrow">{selectedFile.path}</span>
                <button
                  type="button"
                  className={`btn btn-sm${editing ? " btn-primary" : ""}`}
                  disabled={saving || selectedInstruction === null}
                  onClick={() => {
                    if (editing) {
                      void saveSelectedInstruction();
                    } else if (selectedInstruction !== null) {
                      setDraft(selectedInstruction.content);
                      editingRef.current = true;
                      setEditing(true);
                      setSaveError(null);
                      setSavedVersion(null);
                    }
                  }}
                >
                  {editing ? "Save" : "Edit"}
                </button>
              </div>
              <div className="panel-body">
                {selectedInstruction === null ? (
                  <div className="page-note">This instruction file is no longer available.</div>
                ) : editing ? (
                  <label className="field">
                    <span className="field-label">Content</span>
                    <textarea
                      className="field-input field-textarea"
                      rows={12}
                      spellCheck={false}
                      disabled={saving}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                  </label>
                ) : (
                  <div className="diff">
                    <div className="diff-head">
                      <span>{selectedFile.path}</span>
                      <span>current</span>
                    </div>
                    <div className="diff-body">
                      {selectedInstruction.content.split("\n").map((line, lineIndex) => (
                        <div className="dl" key={lineIndex}>
                          <span className="dl-mark"> </span>
                          <span>{line}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {saveError === null ? null : <div className="form-error">{saveError}</div>}
                {savedVersion === null ? null : (
                  <div className="page-note">Saved · version {savedVersion}</div>
                )}
              </div>
            </div>
          ) : null}

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
                <div className="review-actions">
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
