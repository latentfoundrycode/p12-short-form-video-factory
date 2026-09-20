// Frozen contract — Stage P, P-9c: the registry-backed single-select has a loading state.
//
// P-9b left the single-select without a dedicated loading branch: while the options fetch is in
// flight, `options` is empty, so a param with a VALID default id computed `currentWasRemoved` and
// briefly rendered that id as "<id> (removed)". P-9c gives the select a loading cue (parity with the
// multiselect arm) and suppresses the removed-marker while loading, so a valid default never flashes
// as removed.
//
// The fetch is mocked to never resolve, pinning the component in the loading state for assertion.

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RunLaunchForm } from "./RunLaunchForm";
import type { Param } from "../types";

vi.mock("../api", () => ({
  startRun: vi.fn(),
  fetchProviderOptions: vi.fn(),
}));

import { fetchProviderOptions } from "../api";

const mockFetchOptions = vi.mocked(fetchProviderOptions);

afterEach(() => {
  vi.clearAllMocks();
});

function modelParam(overrides: Partial<Param> = {}): Param {
  return {
    key: "model",
    type: "select",
    label: "Model",
    required: false,
    default: null,
    help: null,
    affects_cost: false,
    min: null,
    max: null,
    step: null,
    options: null,
    options_from: "sfvf.models:video",
    placeholder: null,
    unit: null,
    ...overrides,
  };
}

describe("RunLaunchForm registry select loading state", () => {
  it("shows a loading cue and does not flash a valid default as removed", () => {
    // Never resolves: the field stays in its loading state.
    mockFetchOptions.mockReturnValue(new Promise<never>(() => {}));
    render(
      <RunLaunchForm
        workflowId="wf"
        workflowName="WF"
        params={[modelParam({ default: "byteplus/seedance-2.5" })]}
        onStarted={vi.fn()}
        onCancel={() => {}}
      />,
    );

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    expect(screen.queryByText(/removed/i)).toBeNull();
  });
});
