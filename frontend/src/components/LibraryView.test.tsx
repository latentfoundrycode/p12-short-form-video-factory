// Frozen contract / Tier-A observability — TASK-SSN-A7: the Library tab view.
//
// LibraryView backs the new Library tab. It fetches the owner-pool assets and the workflow list
// (via api.fetchLibraryAssets / api.fetchLibraryWorkflows), and renders the inventory states from
// the Phase-1 inventory:
//   - dense: a row per asset showing its NAME, kind, and an access summary
//       ("All workflows" for {all:true}; the workflow label / "N workflows" for a specific grant)
//   - empty: a message that no assets are loaded (videos play narration-only until some are added)
//   - error: a load failure with a Retry control
// Observability invariants (baseline): no console.error across any state; nothing rendered as
// "undefined" / "NaN" / "[object Object]".
//
// The API is mocked (no network). Supervisor-authored frozen contract (RED-first); the builder
// implements LibraryView.tsx + the api helpers.

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LibraryView } from "./LibraryView";

vi.mock("../api", () => ({
  fetchLibraryAssets: vi.fn(),
  fetchLibraryWorkflows: vi.fn(),
}));

import { fetchLibraryAssets, fetchLibraryWorkflows } from "../api";

const mockAssets = vi.mocked(fetchLibraryAssets);
const mockWorkflows = vi.mocked(fetchLibraryWorkflows);

let errorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  mockWorkflows.mockResolvedValue([{ id: "sensational-science-news", label: "Sensational Science News" }]);
});

afterEach(() => {
  vi.clearAllMocks();
  errorSpy.mockRestore();
});

function noPlaceholders(): void {
  const text = document.body.textContent ?? "";
  expect(text).not.toContain("undefined");
  expect(text).not.toContain("NaN");
  expect(text).not.toContain("[object Object]");
}

describe("LibraryView", () => {
  it("dense: renders a row per asset with name, kind and access summary", async () => {
    mockAssets.mockResolvedValue([
      {
        id: "a".repeat(64),
        name: "Cosmic Drift",
        kind: "music",
        status: "active",
        facets: { mood: "wonder" },
        description: "",
        grant: { all: true },
      },
      {
        id: "b".repeat(64),
        name: "Whoosh",
        kind: "sfx",
        status: "active",
        facets: {},
        description: "",
        grant: { workflows: ["sensational-science-news"] },
      },
    ]);
    render(<LibraryView />);
    await waitFor(() => expect(screen.getByText("Cosmic Drift")).toBeTruthy());
    expect(screen.getByText("Whoosh")).toBeTruthy();
    // access summary: {all:true} reads as "All workflows"; specific grant names the workflow.
    expect(screen.getByText(/all workflows/i)).toBeTruthy();
    expect(screen.getByText(/sensational science news/i)).toBeTruthy();
    expect(errorSpy).not.toHaveBeenCalled();
    noPlaceholders();
  });

  it("empty: shows a no-assets message", async () => {
    mockAssets.mockResolvedValue([]);
    render(<LibraryView />);
    await waitFor(() => expect(screen.getByText(/no assets/i)).toBeTruthy());
    expect(errorSpy).not.toHaveBeenCalled();
    noPlaceholders();
  });

  it("error: shows a load failure with a Retry control, no console.error", async () => {
    mockAssets.mockRejectedValue(new Error("network down"));
    render(<LibraryView />);
    await waitFor(() => expect(screen.getByText(/retry/i)).toBeTruthy());
    expect(errorSpy).not.toHaveBeenCalled(); // the failure is handled in the UI, not logged
    noPlaceholders();
  });
});
