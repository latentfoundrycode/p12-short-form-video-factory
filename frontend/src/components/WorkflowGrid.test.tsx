// Frozen contract - F2b-frontend fix: the finished-green "seen" state is owned by App (survives the
// grid unmounting when the video list opens) and is keyed by last_run.run_id, so a NEW run re-greens.
// WorkflowGrid receives `openedRuns` (a set of opened run ids) and computes each card's `seen`; the
// Runs button reports the workflow id AND its current last_run.run_id so App can record it.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Workflow } from "../types";
import { WorkflowGrid } from "./WorkflowGrid";

vi.mock("../api", () => ({
  fetchWorkflows: vi.fn(),
  rescanWorkflows: vi.fn(),
}));

import { fetchWorkflows } from "../api";

const mockFetch = vi.mocked(fetchWorkflows);

function finishedWorkflow(runId: string): Workflow {
  return {
    id: "alpha",
    name: "Alpha Workflow",
    description: null,
    thumbnail_url: null,
    valid: true,
    problems: [],
    quality_factors: [],
    params: [],
    avg_cost_per_meter: {},
    runs_counted: 1,
    archived: false,
    last_run: { run_id: runId, status: "complete", stage: null, progress: null },
  } as Workflow;
}

function grid(openedRuns: Set<string>, onViewRuns = vi.fn()) {
  return render(
    <WorkflowGrid
      onCount={vi.fn()}
      onStarted={vi.fn()}
      onViewRuns={onViewRuns}
      openedRuns={openedRuns}
    />,
  );
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("WorkflowGrid finished-green seen tracking", () => {
  it("a finished card is green when its run id is not in openedRuns", async () => {
    mockFetch.mockResolvedValue([finishedWorkflow("r1")]);
    const { container } = grid(new Set());
    await screen.findByText("Alpha Workflow");
    expect(container.querySelector("article")?.className).toContain("s-done");
  });

  it("the same finished run is cleared once its run id is in openedRuns", async () => {
    mockFetch.mockResolvedValue([finishedWorkflow("r1")]);
    const { container } = grid(new Set(["r1"]));
    await screen.findByText("Alpha Workflow");
    expect(container.querySelector("article")?.className).not.toContain("s-done");
  });

  it("a newer run id re-greens even after an older one was opened", async () => {
    mockFetch.mockResolvedValue([finishedWorkflow("r2")]);
    const { container } = grid(new Set(["r1"]));
    await screen.findByText("Alpha Workflow");
    expect(container.querySelector("article")?.className).toContain("s-done");
  });

  it("opening Runs reports the workflow id and its current run id", async () => {
    mockFetch.mockResolvedValue([finishedWorkflow("r1")]);
    const onViewRuns = vi.fn();
    grid(new Set(), onViewRuns);
    await screen.findByText("Alpha Workflow");
    await userEvent.click(screen.getByRole("button", { name: /^runs$/i }));
    expect(onViewRuns).toHaveBeenCalledWith("alpha", "r1");
  });
});
