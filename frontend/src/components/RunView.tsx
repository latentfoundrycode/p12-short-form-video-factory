import { useEffect, useRef, useState } from "react";
import { fetchRun, runEventsUrl, stopRun } from "../api";
import type {
  RequestStatus,
  RunDetail,
  SseEnvelope,
  StageEvent,
  VideoStatus,
} from "../types";
import { isTerminalStatus } from "../types";

type RunViewProps = {
  workflowId: string;
  runId: string;
  onClose: () => void;
};

function messageOf(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

function statusPillClass(status: RequestStatus): string {
  switch (status) {
    case "running":
      return "pill run";
    case "complete":
      return "pill done";
    case "failed":
      return "pill fail";
    case "partial":
    case "stopped":
    case "stopped-budget":
      return "pill warn";
    default:
      return "pill";
  }
}

function videoPillClass(status: VideoStatus): string {
  switch (status) {
    case "running":
      return "pill run";
    case "complete":
      return "pill done";
    case "failed":
      return "pill fail";
    case "stopped":
      return "pill warn";
    case "pending":
    default:
      return "pill idle";
  }
}

function isStageEvent(event: SseEnvelope["event"]): event is StageEvent {
  return event.t === "stage";
}

function strField(event: Record<string, unknown>, key: string): string {
  const value = event[key];
  return value == null ? "" : String(value);
}

function formatEnvelope(envelope: SseEnvelope): string {
  const event = envelope.event as Record<string, unknown>;
  const t = String(event.t ?? "unknown");
  switch (t) {
    case "stage":
      return `stage ${strField(event, "index")}/${strField(event, "total")} — ${strField(event, "label")}`;
    case "log":
      return `log [${strField(event, "level")}] ${strField(event, "msg")}`;
    case "cost": {
      const note = event.note != null ? ` — ${String(event.note)}` : "";
      return `cost ${strField(event, "meter")} ${strField(event, "amount")} ${strField(event, "unit")}${note}`;
    }
    case "progress":
      return `progress ${strField(event, "family")} ${strField(event, "done")}/${strField(event, "total")}`;
    case "heartbeat":
      return `heartbeat ${strField(event, "name")} waiting on ${strField(event, "waiting_on")}`;
    case "step":
      return `step ${strField(event, "name")} (${strField(event, "key")}) ${strField(event, "label")} — ${strField(event, "status")}`;
    case "result": {
      const caption = event.caption != null ? ` caption=${String(event.caption)}` : "";
      return `result video=${JSON.stringify(event.video)}${caption}`;
    }
    default:
      return `${t}: ${JSON.stringify(event)}`;
  }
}

export function RunView({ workflowId, runId, onClose }: RunViewProps) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stopError, setStopError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const [events, setEvents] = useState<SseEnvelope[]>([]);
  const [stage, setStage] = useState<StageEvent | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchRun(workflowId, runId).then(
      (detail) => {
        if (!cancelled) {
          setRun(detail);
          setLoadError(null);
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setLoadError(messageOf(err, "Could not load run"));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [workflowId, runId]);

  useEffect(() => {
    const source = new EventSource(runEventsUrl(workflowId, runId));
    let closedByUs = false;

    source.onopen = () => {
      // Every (re)connect replays the full history — reset so the list is not doubled.
      setEvents([]);
      setStage(null);
    };

    source.onmessage = (message) => {
      let envelope: SseEnvelope;
      try {
        envelope = JSON.parse(message.data as string) as SseEnvelope;
      } catch {
        return;
      }
      if (
        typeof envelope !== "object" ||
        envelope === null ||
        typeof envelope.ts !== "string" ||
        typeof envelope.source !== "string" ||
        typeof envelope.event !== "object" ||
        envelope.event === null ||
        typeof envelope.event.t !== "string"
      ) {
        return;
      }
      setEvents((prev) => [...prev, envelope]);
      if (isStageEvent(envelope.event)) {
        setStage(envelope.event);
      }
    };

    source.onerror = () => {
      if (closedByUs) {
        return;
      }
      void fetchRun(workflowId, runId).then(
        (detail) => {
          setRun(detail);
          setLoadError(null);
          if (isTerminalStatus(detail.status)) {
            closedByUs = true;
            source.close();
          }
          // If still running, leave EventSource alone so it can reconnect.
        },
        (err: unknown) => {
          setLoadError(messageOf(err, "Could not refresh run after stream error"));
        },
      );
    };

    return () => {
      closedByUs = true;
      source.close();
    };
  }, [workflowId, runId]);

  useEffect(() => {
    const el = feedRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [events]);

  const active = run !== null && !isTerminalStatus(run.status);

  async function onStop(mode: "graceful" | "hard") {
    setStopError(null);
    setStopping(true);
    try {
      await stopRun(workflowId, runId, mode);
      const detail = await fetchRun(workflowId, runId);
      setRun(detail);
    } catch (err) {
      setStopError(messageOf(err, "Could not stop run"));
    } finally {
      setStopping(false);
    }
  }

  return (
    <section className="view on">
      <div className="page-head">
        <div>
          <div className="page-title">Run {runId}</div>
          <div className="page-note">
            Live progress for <span className="path">{workflowId}</span>. State comes from the
            backend; this view holds none of its own.
          </div>
        </div>
        <button type="button" className="btn btn-sm" onClick={onClose}>
          Close
        </button>
      </div>

      {loadError && !run ? (
        <div className="panel">
          <div className="panel-body">
            <div className="page-note">{loadError}</div>
          </div>
        </div>
      ) : null}

      {run ? (
        <div className="run-layout">
          <div className="panel">
            <div className="panel-head">
              <span className="eyebrow">Status</span>
              <span className={statusPillClass(run.status)}>{run.status}</span>
            </div>
            <div className="panel-body">
              <div className="run-meta">
                <div>
                  <span className="field-label">Started</span>
                  <span className="path">{run.started_utc}</span>
                </div>
                {run.ended_utc ? (
                  <div>
                    <span className="field-label">Ended</span>
                    <span className="path">{run.ended_utc}</span>
                  </div>
                ) : null}
              </div>

              <div className="run-stage">
                <span className="field-label">Current stage</span>
                {stage ? (
                  <div className="run-stage-value">
                    {stage.index}/{stage.total} — {stage.label}
                  </div>
                ) : (
                  <div className="page-note">No stage event yet.</div>
                )}
              </div>

              <div className="run-videos">
                <span className="field-label">Videos</span>
                <div className="run-video-list">
                  {run.videos.map((video) => (
                    <span key={video.index} className={videoPillClass(video.status)}>
                      #{video.index} {video.status}
                    </span>
                  ))}
                  {run.videos.length === 0 ? (
                    <span className="page-note">No videos recorded yet.</span>
                  ) : null}
                </div>
              </div>

              {stopError ? <div className="form-error">{stopError}</div> : null}
              {loadError ? <div className="form-error">{loadError}</div> : null}

              <div className="card-foot launch-actions">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!active || stopping}
                  onClick={() => {
                    void onStop("graceful");
                  }}
                >
                  Stop
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!active || stopping}
                  onClick={() => {
                    void onStop("hard");
                  }}
                >
                  Force stop
                </button>
              </div>
            </div>
          </div>

          <div className="panel run-feed-panel">
            <div className="panel-head">
              <span className="eyebrow">Live event feed</span>
              <span className="page-note">{events.length} event{events.length === 1 ? "" : "s"}</span>
            </div>
            <div className="panel-body run-feed" ref={feedRef}>
              {events.length === 0 ? (
                <div className="page-note">Waiting for events…</div>
              ) : (
                <ul className="event-list">
                  {events.map((envelope, index) => (
                    <li key={`${envelope.ts}-${index}`} className="event-row">
                      <span className="event-ts path">{envelope.ts}</span>
                      <span className="event-src">{envelope.source}</span>
                      <span className="event-body">{formatEnvelope(envelope)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
