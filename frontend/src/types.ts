export type Problem = {
  code: string;
  message: string;
  severity: "error" | "warning";
};

export type Workflow = {
  id: string;
  name: string | null;
  description: string | null;
  thumbnail_url: string | null;
  valid: boolean;
  problems: Problem[];
};

export type WorkflowList = {
  workflows: Workflow[];
};

export type RequestStatus =
  | "running"
  | "complete"
  | "partial"
  | "stopped"
  | "stopped-budget"
  | "failed";

export type VideoStatus = "pending" | "running" | "complete" | "failed" | "stopped";

export type StopMode = "graceful" | "hard";

export type WorkflowRef = {
  id: string;
  version: string;
  sdk: string;
};

export type VideoRef = {
  index: number;
  status: VideoStatus;
};

export type VideoRecord = {
  index: number;
  status: VideoStatus;
  started_utc: string;
  ended_utc: string | null;
  cost?: Record<string, unknown> | null;
  steps?: unknown[] | null;
  instructions?: Record<string, unknown> | null;
  library?: unknown[] | null;
  gates?: unknown[] | null;
  decisions?: unknown[] | null;
  artifacts?: unknown[] | null;
  self_review?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  quality?: Record<string, unknown> | null;
  error?: unknown | null;
};

export type RunSummary = {
  run_id: string;
  status: RequestStatus;
  started_utc: string;
  ended_utc: string | null;
  videos: VideoRef[];
};

export type RunList = {
  runs: RunSummary[];
};

export type RunDetail = {
  run_id: string;
  workflow: WorkflowRef;
  started_utc: string;
  ended_utc: string | null;
  status: RequestStatus;
  params: Record<string, unknown>;
  params_locked_utc: string;
  videos: VideoRef[];
  video_records: VideoRecord[];
  budget?: Record<string, unknown> | null;
  forecast?: Record<string, unknown> | null;
};

export type LaunchBody = {
  params: Record<string, unknown>;
  video_count: number;
  concurrency: number;
};

export type StartRunOk = { run_id: string };
export type StartRunErr = { error: string; status: 409 | 422 | number };
export type StartRunResult = StartRunOk | StartRunErr;

export type StopRunResult = {
  run_id: string;
  mode: StopMode;
};

/** Typed shapes for known `event.t` values; unknown types stay generic. */
export type StageEvent = { t: "stage"; index: number; total: number; label: string };
export type LogEvent = { t: "log"; level: string; msg: string };
export type CostEvent = { t: "cost"; meter: string; unit: string; amount: number; note?: string };
export type ProgressEvent = { t: "progress"; family: string; done: number; total: number };
export type HeartbeatEvent = { t: "heartbeat"; name: string; waiting_on: string };
export type StepEvent = { t: "step"; name: string; key: string; label: string; status: string };
export type ResultEvent = { t: "result"; video: unknown; caption?: string };
export type GenericRunEvent = { t: string; [key: string]: unknown };

export type RunEvent =
  | StageEvent
  | LogEvent
  | CostEvent
  | ProgressEvent
  | HeartbeatEvent
  | StepEvent
  | ResultEvent
  | GenericRunEvent;

export type SseEnvelope = {
  ts: string;
  source: string;
  event: RunEvent;
};

export const TERMINAL_STATUSES: ReadonlySet<RequestStatus> = new Set([
  "complete",
  "partial",
  "stopped",
  "stopped-budget",
  "failed",
]);

export function isTerminalStatus(status: RequestStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}

export function isStartRunOk(result: StartRunResult): result is StartRunOk {
  return "run_id" in result;
}
