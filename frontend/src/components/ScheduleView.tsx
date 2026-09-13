import { useEffect, useState, type FormEvent } from "react";
import {
  createSchedule,
  deleteSchedule,
  fetchSchedules,
  fetchWorkflows,
  updateSchedule,
} from "../api";
import type { ScheduleEntry, ScheduleWriteBody, Workflow } from "../types";

const DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"] as const;
const DAY_NAMES = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;
const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d$/;

type ScheduleFormProps = {
  workflows: Workflow[];
  entry: ScheduleEntry | null;
  onCancel: () => void;
  onSaved: () => void;
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function parseParamsObject(
  raw: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
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

function ScheduleForm({ workflows, entry, onCancel, onSaved }: ScheduleFormProps) {
  const [workflowId, setWorkflowId] = useState(entry?.workflow_id ?? workflows[0]?.id ?? "");
  const [days, setDays] = useState<number[]>(entry ? [...entry.days] : []);
  const [timeOfDay, setTimeOfDay] = useState(entry?.time_of_day ?? "");
  const [videoCount, setVideoCount] = useState(entry?.video_count ?? 1);
  const [concurrency, setConcurrency] = useState(entry?.concurrency ?? 1);
  const [gatesAuto, setGatesAuto] = useState(entry?.gates_auto ?? false);
  const [allowRealSpend, setAllowRealSpend] = useState(entry?.allow_real_spend ?? false);
  const [paramsText, setParamsText] = useState(
    entry ? JSON.stringify(entry.params, null, 2) : "{}",
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function toggleDay(day: number) {
    setDays((current) =>
      current.includes(day)
        ? current.filter((candidate) => candidate !== day)
        : [...current, day].sort((a, b) => a - b),
    );
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);

    if (!workflowId || !workflows.some((workflow) => workflow.id === workflowId)) {
      setFormError("Select a workflow.");
      return;
    }
    if (days.length === 0) {
      setFormError("Select at least one day.");
      return;
    }
    if (!TIME_PATTERN.test(timeOfDay)) {
      setFormError("Time must use 24-hour HH:MM format.");
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
    const parsed = parseParamsObject(paramsText);
    if (!parsed.ok) {
      setFormError(parsed.error);
      return;
    }

    const body: ScheduleWriteBody = {
      workflow_id: workflowId,
      days,
      time_of_day: timeOfDay,
      video_count: videoCount,
      concurrency,
      params: parsed.value,
      gates_auto: gatesAuto,
      allow_real_spend: allowRealSpend,
    };

    setSubmitting(true);
    try {
      if (entry) {
        await updateSchedule(entry.id, body);
      } else {
        await createSchedule(body);
      }
      onSaved();
    } catch (err) {
      setFormError(messageOf(err, "Could not save schedule"));
    } finally {
      setSubmitting(false);
    }
  }

  async function onDelete() {
    if (!entry || !window.confirm("Delete this schedule entry?")) {
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      await deleteSchedule(entry.id);
      onSaved();
    } catch (err) {
      setFormError(messageOf(err, "Could not delete schedule"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <span className="eyebrow">{entry ? "Edit entry" : "Add entry"}</span>
          <div className="launch-title">{entry ? "Edit schedule" : "New schedule"}</div>
        </div>
      </div>
      <form className="panel-body launch-form" onSubmit={(event) => void onSubmit(event)}>
        <label className="field">
          <span className="field-label">Workflow</span>
          <select
            className="sel"
            value={workflowId}
            disabled={submitting}
            onChange={(event) => {
              setWorkflowId(event.target.value);
            }}
          >
            {workflows.length === 0 ? <option value="">No valid workflows</option> : null}
            {workflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>
                {workflow.name || workflow.id}
              </option>
            ))}
          </select>
        </label>

        <div className="field">
          <span className="field-label">Days</span>
          <div className="days">
            {DAY_LABELS.map((label, index) => (
              <button
                key={DAY_NAMES[index]}
                type="button"
                className={days.includes(index) ? "day on" : "day"}
                aria-label={DAY_NAMES[index]}
                aria-pressed={days.includes(index)}
                disabled={submitting}
                onClick={() => {
                  toggleDay(index);
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <label className="field">
          <span className="field-label">Time</span>
          <input
            className="field-input"
            type="time"
            value={timeOfDay}
            disabled={submitting}
            onChange={(event) => {
              setTimeOfDay(event.target.value);
            }}
          />
        </label>

        <label className="field">
          <span className="field-label">Video count</span>
          <input
            className="field-input"
            type="number"
            min={1}
            step={1}
            value={videoCount}
            disabled={submitting}
            onChange={(event) => {
              setVideoCount(Number(event.target.value));
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
            onChange={(event) => {
              setConcurrency(Number(event.target.value));
            }}
          />
        </label>

        <div className="switch">
          <span>{gatesAuto ? "Gates pass automatically" : "Pauses at gates"}</span>
          <button
            type="button"
            className={gatesAuto ? "tog on" : "tog"}
            aria-label="Pass approval gates automatically"
            aria-pressed={gatesAuto}
            disabled={submitting}
            onClick={() => {
              setGatesAuto((current) => !current);
            }}
          />
        </div>

        <div className="switch">
          <span>{allowRealSpend ? "Spends real money" : "Free dry run"}</span>
          <button
            type="button"
            className={allowRealSpend ? "tog on" : "tog"}
            aria-label="Allow real spend"
            aria-pressed={allowRealSpend}
            disabled={submitting}
            onClick={() => {
              setAllowRealSpend((current) => !current);
            }}
          />
        </div>

        {allowRealSpend ? (
          <div className="blocker">This schedule will spend real money on each run.</div>
        ) : null}

        <label className="field">
          <span className="field-label">Params (JSON object)</span>
          <textarea
            className="field-input field-textarea"
            rows={5}
            spellCheck={false}
            value={paramsText}
            disabled={submitting}
            onChange={(event) => {
              setParamsText(event.target.value);
            }}
          />
        </label>

        {formError ? <div className="form-error">{formError}</div> : null}

        <div className="card-foot launch-actions">
          <button type="submit" className="btn btn-primary btn-sm" disabled={submitting}>
            {submitting ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={submitting}
            onClick={onCancel}
          >
            Cancel
          </button>
          {entry ? (
            <button
              type="button"
              className="btn btn-sm"
              disabled={submitting}
              onClick={() => void onDelete()}
            >
              Delete
            </button>
          ) : null}
        </div>
      </form>
    </div>
  );
}

export function ScheduleView() {
  const [schedules, setSchedules] = useState<ScheduleEntry[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [formEntry, setFormEntry] = useState<ScheduleEntry | "create" | null>(null);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchSchedules(), fetchWorkflows()]).then(
      ([nextSchedules, nextWorkflows]) => {
        if (!cancelled) {
          setSchedules(nextSchedules);
          setWorkflows(nextWorkflows);
          setStatus("ready");
          setError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setSchedules([]);
          setWorkflows([]);
          setStatus("error");
          setError(messageOf(err, "Could not load schedules"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const validWorkflows = workflows.filter((workflow) => workflow.valid);

  function reload() {
    setFormEntry(null);
    setStatus("loading");
    setError(null);
    setReloadKey((key) => key + 1);
  }

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Schedule</div>
          <div className="page-note">
            A slot is skipped if the workflow is still running or the budget is short. Missed slots
            are not queued.
          </div>
        </div>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          disabled={status !== "ready" || formEntry !== null}
          onClick={() => {
            setFormEntry("create");
          }}
        >
          Add entry
        </button>
      </div>

      {formEntry !== null ? (
        <ScheduleForm
          key={formEntry === "create" ? "create" : formEntry.id}
          workflows={validWorkflows}
          entry={formEntry === "create" ? null : formEntry}
          onCancel={() => {
            setFormEntry(null);
          }}
          onSaved={reload}
        />
      ) : null}

      {formEntry === null && status === "loading" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">Loading schedules…</div>
          </div>
        </div>
      ) : null}

      {formEntry === null && status === "error" ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">{error}</div>
            <div className="card-foot">
              <button type="button" className="btn btn-sm" onClick={reload}>
                Retry
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {formEntry === null && status === "ready" && schedules.length === 0 ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">No schedules yet.</div>
          </div>
        </div>
      ) : null}

      {formEntry === null && status === "ready" && schedules.length > 0 ? (
        <div className="panel">
          <ul className="list">
            {schedules.map((entry) => {
              const workflow = workflows.find((candidate) => candidate.id === entry.workflow_id);
              const videoLabel =
                entry.video_count === 1 ? "1 video" : `${entry.video_count} videos`;
              const concurrencyLabel =
                entry.concurrency > 1 ? `, ${entry.concurrency} at a time` : "";
              const spendLabel = entry.allow_real_spend ? "spends real money" : "dry run (free)";
              return (
                <li className="li" key={entry.id}>
                  <div className="li-main">
                    <div className="li-title">{workflow?.name || entry.workflow_id}</div>
                    <div className="li-sub">
                      {videoLabel}
                      {concurrencyLabel} · {spendLabel}
                    </div>
                    <div className="li-sub">
                      {entry.gates_auto ? "Gates pass automatically" : "Pauses at gates"}
                    </div>
                  </div>
                  <div className="days" aria-label="Scheduled days">
                    {DAY_LABELS.map((label, index) => (
                      <span
                        className={entry.days.includes(index) ? "day on" : "day"}
                        key={DAY_NAMES[index]}
                        title={DAY_NAMES[index]}
                      >
                        {label}
                      </span>
                    ))}
                  </div>
                  <div className="time">{entry.time_of_day}</div>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => {
                      setFormEntry(entry);
                    }}
                  >
                    Edit
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
