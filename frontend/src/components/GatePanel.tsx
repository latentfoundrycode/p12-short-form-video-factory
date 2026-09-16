import { useEffect, useState } from "react";
import { fetchPendingGates, runFileUrl, submitGate } from "../api";
import type { PendingGate } from "../types";

type GatePanelProps = {
  workflowId: string;
  runId: string;
  gateEventCount: number;
  onResolved: () => void;
};

type LoadStatus = "loading" | "ready" | "error";

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function GatePanel({ workflowId, runId, gateEventCount, onResolved }: GatePanelProps) {
  const [gates, setGates] = useState<PendingGate[]>([]);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [redo, setRedo] = useState<Set<string>>(() => new Set());
  const [note, setNote] = useState("");
  const [shownGateToken, setShownGateToken] = useState<string | undefined>();
  const [refreshKey, setRefreshKey] = useState(0);
  const gate = gates[0];

  useEffect(() => {
    let cancelled = false;
    void fetchPendingGates(workflowId, runId).then(
      (pending) => {
        if (!cancelled) {
          setGates(pending);
          setStatus("ready");
          setError(null);
        }
      },
      (fetchError: unknown) => {
        if (!cancelled) {
          setStatus("error");
          setError(messageOf(fetchError, "Could not load gates"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [workflowId, runId, gateEventCount, refreshKey]);

  if (gate?.token !== shownGateToken) {
    setShownGateToken(gate?.token);
    setRedo(new Set());
    setNote("");
    setSubmitError(null);
  }

  if (status === "error") {
    return (
      <div className="panel launch-panel">
        <div className="panel-head">
          <span className="eyebrow">Decision needed</span>
        </div>
        <div className="panel-body">
          <div className="form-error">{error}</div>
        </div>
      </div>
    );
  }

  if (!gate) {
    return null;
  }

  async function submit(decision: unknown) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitGate(workflowId, runId, gate.video, gate.token, decision);
      setRedo(new Set());
      setNote("");
      onResolved();
      setRefreshKey((current) => current + 1);
    } catch (submitFailure) {
      setSubmitError(messageOf(submitFailure, "Could not submit decision"));
    } finally {
      setSubmitting(false);
    }
  }

  function toggleRedo(id: string) {
    setRedo((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  const items = gate.items ?? [];

  return (
    <div className="panel launch-panel">
      <div className="panel-head">
        <span className="eyebrow">Decision needed</span>
        {status === "loading" ? <span className="page-note">Loading…</span> : null}
      </div>
      <div className="panel-body">
        <div className="gate-title">{gate.prompt}</div>

        {gate.shape === "approval" && gate.payload !== undefined ? (
          <div className="diff">
            <div className="diff-body">
              {(JSON.stringify(gate.payload, null, 2) ?? "").split("\n").map((line, index) => (
                <div className="dl" key={index}>
                  <span className="dl-mark"> </span>
                  <span>{line}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {gate.shape === "selection" ? (
          <>
            <div className="gate-items">
              {items.map((item) => (
                <div className={`gate-item${redo.has(item.id) ? " redo" : ""}`} key={item.id}>
                  {item.artifact ? (
                    <img
                      className="gate-item-img"
                      src={runFileUrl(workflowId, runId, `${gate.video}/${item.artifact}`)}
                      alt={item.label ?? item.id}
                    />
                  ) : null}
                  <div className="card-title">{item.label ?? item.id}</div>
                  <label className="field-check">
                    <input
                      type="checkbox"
                      checked={redo.has(item.id)}
                      disabled={submitting}
                      onChange={() => toggleRedo(item.id)}
                    />
                    <span>Redo</span>
                  </label>
                </div>
              ))}
            </div>
            <label className="field">
              <span className="field-label">Note (optional)</span>
              <textarea
                className="field-input field-textarea"
                value={note}
                disabled={submitting}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
          </>
        ) : null}

        {error ? <div className="form-error">{error}</div> : null}
        {submitError ? <div className="form-error">{submitError}</div> : null}

        <div className="card-foot launch-actions">
          {gate.shape === "approval" ? (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={submitting}
                onClick={() => {
                  void submit({ choice: "approve" });
                }}
              >
                Approve
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={submitting}
                onClick={() => {
                  void submit({ choice: "reject" });
                }}
              >
                Reject
              </button>
            </>
          ) : null}

          {gate.shape === "choice"
            ? (gate.options ?? []).map((option) => (
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={submitting}
                  key={option}
                  onClick={() => {
                    void submit({ choice: option });
                  }}
                >
                  {option}
                </button>
              ))
            : null}

          {gate.shape === "selection" ? (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={submitting}
                onClick={() => {
                  void submit({
                    choice: "approve",
                    keep: items.filter((item) => !redo.has(item.id)).map((item) => item.id),
                    redo: items.filter((item) => redo.has(item.id)).map((item) => item.id),
                    note,
                  });
                }}
              >
                Approve
              </button>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                disabled={submitting}
                onClick={() => {
                  void submit({ choice: "reject", note });
                }}
              >
                Reject
              </button>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
