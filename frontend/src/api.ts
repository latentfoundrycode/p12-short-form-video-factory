import type { Workflow, WorkflowList } from "./types";

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
