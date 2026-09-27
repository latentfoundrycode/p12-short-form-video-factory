// Frozen contract - F2b-frontend: the main-tab WorkflowCard rendering (PRD §8.1, R-005..R-011).
//
// Outline/state decision order (first match wins):
//   archived -> "card s-arch" (grey, pill "Archived", Runs/Browse only, NO Run button) [R-011]
//   !valid (not archived) -> "card s-fail", pill "Broken", problem messages [R-013]
//   last_run.status running -> "card s-run", pill "Running", stage line "i / total — label" [R-006/007]
//   last_run.status failed | stopped-budget -> "card s-fail" (needs attention) [R-007/008]
//   last_run.status complete | partial, and NOT yet seen -> "card s-done", pill "Finished" [R-007]
//   otherwise (idle / user-stopped / seen) -> "card", pill "Idle"
// Average cost per meter block (R-005) shows on non-archived cards from avg_cost_per_meter;
// runs_counted === 0 renders a "No runs yet" treatment.
// "seen" (the user opened this workflow's video list) clears the green finished state (R-007).
//
// API/behaviour is prop-driven; the grid supplies `seen` and the run-state. Supervisor-authored
// frozen contract (RED-first); the builder implements WorkflowCard.tsx (+ types/css/grid wiring).

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Workflow } from "../types";
import { WorkflowCard } from "./WorkflowCard";

function make(overrides: Partial<Workflow> = {}): Workflow {
  return {
    id: "sensational-science-news",
    name: "Sensational Science News",
    description: "Repurpose science news into shorts.",
    thumbnail_url: null,
    valid: true,
    problems: [],
    quality_factors: [],
    params: [],
    avg_cost_per_meter: {},
    runs_counted: 0,
    archived: false,
    last_run: null,
    ...overrides,
  } as Workflow;
}

function renderCard(workflow: Workflow, seen = false) {
  const onStarted = vi.fn();
  const onViewRuns = vi.fn();
  const result = render(
    <WorkflowCard workflow={workflow} seen={seen} onStarted={onStarted} onViewRuns={onViewRuns} />,
  );
  return { ...result, onStarted, onViewRuns };
}

function article(container: HTMLElement): HTMLElement {
  const el = container.querySelector("article");
  if (!el) {
    throw new Error("no card article rendered");
  }
  return el as HTMLElement;
}

describe("WorkflowCard", () => {
  it("idle: plain card, Idle pill, Run + Runs buttons", () => {
    const { container } = renderCard(make());
    const cls = article(container).className;
    expect(cls).toContain("card");
    expect(cls).not.toMatch(/s-(run|done|fail|arch)/);
    screen.getByText("Idle");
    screen.getByRole("button", { name: /run workflow/i });
    screen.getByRole("button", { name: /^runs$/i });
  });

  it("shows average cost per meter, and 'No runs yet' when runs_counted is 0", () => {
    const { rerender, container } = renderCard(
      make({ avg_cost_per_meter: { openrouter: 0.29, byteplus: 2.68 }, runs_counted: 5 }),
    );
    expect(container.textContent).toContain("0.29");
    expect(container.textContent).toContain("2.68");
    rerender(
      <WorkflowCard
        workflow={make({ avg_cost_per_meter: {}, runs_counted: 0 })}
        seen={false}
        onStarted={vi.fn()}
        onViewRuns={vi.fn()}
      />,
    );
    expect(container.textContent).toMatch(/no runs yet/i);
  });

  it("running: s-run outline, Running pill, stage line", () => {
    const { container } = renderCard(
      make({
        last_run: {
          run_id: "20260927-000001",
          status: "running",
          stage: { index: 3, total: 7, label: "Generating shots" },
          progress: { done: 37, total: 60 },
        },
      }),
    );
    expect(article(container).className).toContain("s-run");
    screen.getByText("Running");
    expect(container.textContent).toContain("3");
    expect(container.textContent).toContain("7");
    expect(container.textContent).toContain("Generating shots");
  });

  it("finished (complete) shows green until seen, then clears", () => {
    const wf = make({
      last_run: { run_id: "r", status: "complete", stage: null, progress: null },
    });
    const { container, rerender } = renderCard(wf, false);
    expect(article(container).className).toContain("s-done");
    screen.getByText("Finished");
    rerender(
      <WorkflowCard workflow={wf} seen={true} onStarted={vi.fn()} onViewRuns={vi.fn()} />,
    );
    expect(article(container).className).not.toContain("s-done");
  });

  it("partial is treated as finished (green), not an error", () => {
    const { container } = renderCard(
      make({ last_run: { run_id: "r", status: "partial", stage: null, progress: null } }),
    );
    const cls = article(container).className;
    expect(cls).toContain("s-done");
    expect(cls).not.toContain("s-fail");
  });

  it("failed and stopped-budget are red (need attention); user stop is not", () => {
    const failed = renderCard(
      make({ last_run: { run_id: "r", status: "failed", stage: null, progress: null } }),
    );
    expect(article(failed.container).className).toContain("s-fail");
    const budget = renderCard(
      make({ last_run: { run_id: "r", status: "stopped-budget", stage: null, progress: null } }),
    );
    expect(article(budget.container).className).toContain("s-fail");
    const stopped = renderCard(
      make({ last_run: { run_id: "r", status: "stopped", stage: null, progress: null } }),
    );
    const cls = article(stopped.container).className;
    expect(cls).not.toContain("s-fail");
    expect(cls).not.toContain("s-done");
  });

  it("invalid workflow: Broken with problem messages (R-013)", () => {
    const { container } = renderCard(
      make({
        valid: false,
        problems: [{ code: "MISSING_ENTRYPOINT", message: "entrypoint not found", severity: "error" }],
      }),
    );
    expect(article(container).className).toContain("s-fail");
    screen.getByText("Broken");
    screen.getByText(/entrypoint not found/);
  });

  it("archived: greyed, Archived pill, browsable, NOT a red Broken card, no Run button", () => {
    const { container } = renderCard(
      make({
        name: null,
        valid: false,
        archived: true,
        last_run: { run_id: "r", status: "complete", stage: null, progress: null },
      }),
    );
    const cls = article(container).className;
    expect(cls).toContain("s-arch");
    expect(cls).not.toContain("s-fail");
    screen.getByText("Archived");
    expect(screen.queryByText("Broken")).toBeNull();
    // browsable: a runs/browse control exists; no launch button
    screen.getByRole("button", { name: /runs|browse/i });
    expect(screen.queryByRole("button", { name: /run workflow/i })).toBeNull();
  });
});
