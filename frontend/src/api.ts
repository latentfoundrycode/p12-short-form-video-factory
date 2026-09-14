import type {
  AcceptResult,
  LearningList,
  LearningRow,
  LaunchBody,
  QualitySubmission,
  RunDetail,
  RunFiles,
  RunList,
  ScheduleEntry,
  ScheduleList,
  ScheduleWriteBody,
  StagedList,
  StagedProposal,
  StartRunResult,
  Statistics,
  StopMode,
  StopRunResult,
  Workflow,
  WorkflowList,
} from "./types";

async function readList(response: Response, what: string): Promise<Workflow[]> {
  if (!response.ok) {
    throw new Error(`Could not ${what} (${response.status})`);
  }
  const data = (await response.json()) as WorkflowList;
  if (!Array.isArray(data.workflows)) {
    throw new Error(`Unexpected response while trying to ${what}`);
  }
  return data.workflows;
}

export async function fetchWorkflows(): Promise<Workflow[]> {
  return readList(await fetch("/api/workflows"), "load workflows");
}

export async function rescanWorkflows(): Promise<Workflow[]> {
  return readList(await fetch("/api/workflows/rescan", { method: "POST" }), "rescan workflows");
}

export async function fetchLearning(): Promise<LearningRow[]> {
  const response = await fetch("/api/learning");
  if (!response.ok) {
    throw new Error(`Could not load learning data (${response.status})`);
  }
  const data = (await response.json()) as LearningList;
  if (!Array.isArray(data.workflows)) {
    throw new Error("Unexpected response while trying to load learning data");
  }
  return data.workflows;
}

export async function runLearning(id: string): Promise<StagedProposal[]> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/run`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Could not start learning (${response.status})`);
  }
  const data = (await response.json()) as StagedList;
  if (!Array.isArray(data.staged)) {
    throw new Error("Unexpected response while trying to start learning");
  }
  return data.staged;
}

export async function fetchStaged(id: string): Promise<StagedProposal[]> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/staged`);
  if (!response.ok) {
    throw new Error(`Could not load staged proposals (${response.status})`);
  }
  const data = (await response.json()) as StagedList;
  if (!Array.isArray(data.staged)) {
    throw new Error("Unexpected response while trying to load staged proposals");
  }
  return data.staged;
}

export async function acceptLearning(id: string): Promise<string[]> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/accept`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Could not accept learning (${response.status})`);
  }
  const data = (await response.json()) as AcceptResult;
  if (!Array.isArray(data.applied)) {
    throw new Error("Unexpected response while trying to accept learning");
  }
  return data.applied;
}

export async function rejectLearning(id: string): Promise<void> {
  const response = await fetch(`/api/learning/${encodeURIComponent(id)}/reject`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Could not reject learning (${response.status})`);
  }
}

export async function fetchSchedules(): Promise<ScheduleEntry[]> {
  const response = await fetch("/api/schedules");
  if (!response.ok) {
    throw new Error(`Could not load schedules (${response.status})`);
  }
  const data = (await response.json()) as ScheduleList;
  if (!Array.isArray(data.schedules)) {
    throw new Error("Unexpected response while trying to load schedules");
  }
  return data.schedules;
}

export async function createSchedule(body: ScheduleWriteBody): Promise<ScheduleEntry> {
  const response = await fetch("/api/schedules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 201) {
    return (await response.json()) as ScheduleEntry;
  }
  if (response.status === 422) {
    throw new Error("The server rejected these schedule values.");
  }
  throw new Error(`Could not create schedule (${response.status})`);
}

export async function updateSchedule(id: string, body: ScheduleWriteBody): Promise<ScheduleEntry> {
  const response = await fetch(`/api/schedules/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 200) {
    return (await response.json()) as ScheduleEntry;
  }
  if (response.status === 404) {
    throw new Error("That schedule no longer exists.");
  }
  if (response.status === 422) {
    throw new Error("The server rejected these schedule values.");
  }
  throw new Error(`Could not update schedule (${response.status})`);
}

export async function deleteSchedule(id: string): Promise<void> {
  const response = await fetch(`/api/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (response.status === 204) {
    return;
  }
  if (response.status === 404) {
    throw new Error("That schedule no longer exists.");
  }
  throw new Error(`Could not delete schedule (${response.status})`);
}

export function runEventsUrl(workflowId: string, runId: string): string {
  return `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/events`;
}

export async function startRun(id: string, body: LaunchBody): Promise<StartRunResult> {
  const response = await fetch(`/api/workflows/${encodeURIComponent(id)}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (response.status === 202) {
    const data = (await response.json()) as { run_id?: unknown };
    if (typeof data.run_id !== "string" || data.run_id.length === 0) {
      return { error: "Start succeeded but no run id was returned", status: 202 };
    }
    return { run_id: data.run_id };
  }

  if (response.status === 409) {
    const data = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail =
      typeof data?.detail === "string" ? data.detail : "workflow already has an active run";
    return { error: detail, status: 409 };
  }

  if (response.status === 422) {
    const data = (await response.json().catch(() => null)) as {
      reason?: unknown;
      detail?: unknown;
    } | null;
    if (typeof data?.reason === "string" && data.reason.length > 0) {
      return { error: data.reason, status: 422 };
    }
    if (typeof data?.detail === "string" && data.detail.length > 0) {
      return { error: data.detail, status: 422 };
    }
    return { error: "Could not start run (environment blocked or workflow invalid)", status: 422 };
  }

  return { error: `Could not start run (${response.status})`, status: response.status };
}

export async function stopRun(id: string, runId: string, mode: StopMode): Promise<StopRunResult> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/stop`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    },
  );
  if (!response.ok) {
    throw new Error(
      response.status === 404
        ? "Run is not currently running"
        : `Could not stop run (${response.status})`,
    );
  }
  return (await response.json()) as StopRunResult;
}

export async function fetchRun(id: string, runId: string): Promise<RunDetail> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`,
  );
  if (!response.ok) {
    throw new Error(`Could not load run (${response.status})`);
  }
  return (await response.json()) as RunDetail;
}

export async function fetchRunFiles(id: string, runId: string): Promise<RunFiles> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/files`,
  );
  if (!response.ok) {
    throw new Error(`Could not load run files (${response.status})`);
  }
  const data = (await response.json()) as RunFiles;
  if (!Array.isArray(data.files)) {
    throw new Error("Unexpected response while trying to load run files");
  }
  return data;
}

export async function fetchRuns(id: string): Promise<RunList> {
  const response = await fetch(`/api/workflows/${encodeURIComponent(id)}/runs`);
  if (!response.ok) {
    throw new Error(`Could not load runs (${response.status})`);
  }
  const data = (await response.json()) as RunList;
  if (!Array.isArray(data.runs)) {
    throw new Error("Unexpected response while trying to load runs");
  }
  return data;
}

export async function submitQuality(
  workflowId: string,
  runId: string,
  body: QualitySubmission,
): Promise<void> {
  const response = await fetch(
    `/api/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/quality`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (response.ok) {
    return;
  }
  if (response.status === 422) {
    throw new Error("The server rejected these answers.");
  }
  throw new Error(`Could not save judgement (${response.status})`);
}

export async function fetchStatistics(months?: number): Promise<Statistics> {
  const qs = months ? `?months=${encodeURIComponent(months)}` : "";
  const response = await fetch(`/api/statistics${qs}`);
  if (!response.ok) throw new Error(`Could not load statistics (${response.status})`);
  const data = (await response.json()) as Statistics;
  if (!Array.isArray(data.series)) throw new Error("Unexpected statistics response");
  return data;
}
