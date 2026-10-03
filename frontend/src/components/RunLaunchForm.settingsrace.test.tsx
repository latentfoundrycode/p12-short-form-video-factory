// Supervisor test - TASK-102 assumption 2 (R-027/R-030): the Settings load is asynchronous; a value
// the user edits before it resolves must not be overwritten when it does. Settles the builder's
// "Settings defaults apply only while the field still equals the mount snapshot" assumption.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunLaunchForm } from "./RunLaunchForm";

vi.mock("../api", () => ({
  startRun: vi.fn(),
  fetchProviderOptions: vi.fn(),
  fetchVoices: vi.fn(),
  fetchSettings: vi.fn(),
  fetchEstimate: vi.fn(),
}));

import { fetchEstimate, fetchSettings, fetchVoices } from "../api";

function settings(defaultConcurrency: number, defaultStepConcurrency: number) {
  return {
    providers: [],
    configured_secret_names: [],
    allowed_secret_names: [],
    defaults: {
      silence_limit_seconds: { effective: 300, source: "default" },
      default_concurrency: { effective: defaultConcurrency, source: "default" },
      default_step_concurrency: { effective: defaultStepConcurrency, source: "default" },
      cache_max_bytes: { effective: 5368709120, source: "default" },
    },
  };
}

beforeEach(() => {
  vi.mocked(fetchVoices).mockResolvedValue([]);
  vi.mocked(fetchEstimate).mockResolvedValue({
    per_meter: {},
    confidence: "none",
    matches: 0,
    video_count: 1,
  } as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Settings load vs. early user edits (R-027)", () => {
  it("keeps parallel steps and concurrency the user typed before Settings resolved", async () => {
    let resolveSettings: (value: unknown) => void = () => {};
    vi.mocked(fetchSettings).mockReturnValue(
      new Promise((resolve) => {
        resolveSettings = resolve;
      }) as never,
    );
    render(
      <RunLaunchForm
        workflowId="wf"
        workflowName="WF"
        params={[]}
        maxVideos={null}
        onStarted={vi.fn()}
        onCancel={() => {}}
      />,
    );
    const steps = screen.getByLabelText(/parallel steps/i);
    await userEvent.clear(steps);
    await userEvent.type(steps, "2");
    const concurrency = screen.getByLabelText(/^concurrency/i);
    await userEvent.clear(concurrency);
    await userEvent.type(concurrency, "3");

    await act(async () => {
      resolveSettings(settings(5, 6));
      await new Promise((r) => setTimeout(r, 20));
    });

    expect(screen.getByLabelText(/parallel steps/i)).toHaveValue(2);
    expect(screen.getByLabelText(/^concurrency/i)).toHaveValue(3);
  });

  it("still seeds untouched fields when Settings resolve late", async () => {
    let resolveSettings: (value: unknown) => void = () => {};
    vi.mocked(fetchSettings).mockReturnValue(
      new Promise((resolve) => {
        resolveSettings = resolve;
      }) as never,
    );
    render(
      <RunLaunchForm
        workflowId="wf"
        workflowName="WF"
        params={[]}
        maxVideos={null}
        onStarted={vi.fn()}
        onCancel={() => {}}
      />,
    );
    await act(async () => {
      resolveSettings(settings(5, 6));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByLabelText(/parallel steps/i)).toHaveValue(6);
    expect(screen.getByLabelText(/^concurrency/i)).toHaveValue(5);
  });
});
