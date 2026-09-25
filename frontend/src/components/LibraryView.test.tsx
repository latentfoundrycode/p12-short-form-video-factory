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
import userEvent from "@testing-library/user-event";
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
        mood: ["wonder"],
        energy: [],
        description: "",
        grant: { all: true },
      },
      {
        id: "b".repeat(64),
        name: "Whoosh",
        kind: "sfx",
        status: "active",
        mood: [],
        energy: [],
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

  it("accessibility: a mood tag has a keyboard-operable delete control (not right-click-only)", async () => {
    mockAssets.mockResolvedValue([
      {
        id: "a".repeat(64),
        name: "Cosmic Drift",
        kind: "music",
        status: "active",
        mood: ["wonder"],
        energy: [],
        description: "",
        grant: { all: true },
      },
    ]);
    const user = userEvent.setup();
    render(<LibraryView />);
    await waitFor(() => expect(screen.getByText("Cosmic Drift")).toBeTruthy());
    await user.click(screen.getByText("Cosmic Drift")); // open the detail editor
    // Each tag chip must expose an accessible, focusable delete control (a real button reachable by
    // keyboard/AT) whose accessible name references the tag — NOT a right-click-only affordance.
    const del = await screen.findByRole("button", { name: /wonder/i });
    await user.click(del);
    await waitFor(() => expect(screen.queryByText("wonder")).toBeNull());
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("accessibility: entering edit mode moves focus into the edit input (keyboard-operable edit)", async () => {
    mockAssets.mockResolvedValue([
      {
        id: "a".repeat(64),
        name: "Cosmic Drift",
        kind: "music",
        status: "active",
        mood: ["wonder"],
        energy: [],
        description: "",
        grant: { all: true },
      },
    ]);
    const user = userEvent.setup();
    render(<LibraryView />);
    await waitFor(() => expect(screen.getByText("Cosmic Drift")).toBeTruthy());
    await user.click(screen.getByText("Cosmic Drift")); // open the detail editor
    // Focus the chip and start editing via the keyboard (F2). Focus MUST land in the edit
    // input so a keyboard/AT user can type immediately — not fall to document.body.
    const chip = (await screen.findByText("wonder")).closest(".chip") as HTMLElement;
    chip.focus();
    await user.keyboard("{F2}");
    await waitFor(() => {
      const active = document.activeElement as HTMLElement | null;
      expect(active).toBeInstanceOf(HTMLInputElement);
      expect((active as HTMLInputElement).value).toBe("wonder");
    });
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
