import { useState, type FormEvent } from "react";
import { startRun } from "../api";
import { isStartRunOk } from "../types";

type RunLaunchFormProps = {
  workflowId: string;
  workflowName: string;
  onStarted: (runId: string) => void;
  onCancel: () => void;
};

function parseParamsObject(raw: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw) as unknown;
  } catch {
    return { ok: false, error: "Params must be valid JSON." };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: "Params must be a JSON object (e.g. {})." };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

export function RunLaunchForm({
  workflowId,
  workflowName,
  onStarted,
  onCancel,
}: RunLaunchFormProps) {
  const [videoCount, setVideoCount] = useState(1);
  const [concurrency, setConcurrency] = useState(1);
  const [paramsText, setParamsText] = useState("{}");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    const parsed = parseParamsObject(paramsText);
    if (!parsed.ok) {
      setFormError(parsed.error);
      return;
    }
    if (!Number.isInteger(videoCount) || videoCount < 1) {
      setFormError("Video count must be an integer ≥ 1.");
      return;
    }
    if (!Number.isInteger(concurrency) || concurrency < 1) {
      setFormError("Concurrency must be an integer ≥ 1.");
      return;
    }

    setSubmitting(true);
    try {
      const result = await startRun(workflowId, {
        params: parsed.value,
        video_count: videoCount,
        concurrency,
      });
      if (isStartRunOk(result)) {
        onStarted(result.run_id);
        return;
      }
      setFormError(result.error);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not start run");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel launch-panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">Minimal launcher</span>
          <div className="launch-title">Start {workflowName}</div>
        </div>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
      <form className="panel-body launch-form" onSubmit={(e) => void onSubmit(e)}>
        <p className="page-note">
          Temporary controls for video count, concurrency, and raw params JSON. The full
          provider-driven Run pop-up comes later.
        </p>
        <label className="field">
          <span className="field-label">Video count</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={videoCount}
            disabled={submitting}
            onChange={(e) => {
              setVideoCount(Number(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span className="field-label">Concurrency</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={concurrency}
            disabled={submitting}
            onChange={(e) => {
              setConcurrency(Number(e.target.value));
            }}
          />
        </label>
        <label className="field">
          <span className="field-label">Params (JSON object)</span>
          <textarea
            className="field-input field-textarea"
            rows={5}
            spellCheck={false}
            value={paramsText}
            disabled={submitting}
            onChange={(e) => {
              setParamsText(e.target.value);
            }}
          />
        </label>
        {formError ? <div className="form-error">{formError}</div> : null}
        <div className="card-foot launch-actions">
          <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
            {submitting ? "Starting…" : "Start run"}
          </button>
        </div>
      </form>
    </div>
  );
}
