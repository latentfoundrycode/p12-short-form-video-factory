import type {
  LaunchBody,
  RunDetail,
  RunList,
  StartRunResult,
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
    const detail = typeof data?.detail === "string" ? data.detail : "workflow already has an active run";
    return { error: detail, status: 409 };
  }

  if (response.status === 422) {
    const data = (await response.json().catch(() => null)) as
      | { reason?: unknown; detail?: unknown }
      | null;
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

export async function stopRun(
  id: string,
  runId: string,
  mode: StopMode,
): Promise<StopRunResult> {
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
