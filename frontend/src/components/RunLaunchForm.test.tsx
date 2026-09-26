// Frozen contract — Stage P, P-9b: RunLaunchForm renders registry-backed model selects.
//
// A manifest param whose `options_from` is a models source is no longer a manual text box: the form
// fetches `/api/providers/options/{source}` (via api.fetchProviderOptions) and renders a real select
// of models across providers. The §3.7 acceptance (PROVIDER_LAYER_PLAN.md:289-291):
//   - the select submits the `id` and shows the `label`;
//   - unconfigured entries are disabled with a visible suffix;
//   - a recorded-but-removed id (the current value, absent from the options) is shown, marked;
//   - a failed options fetch → manual text input plus a notice;
//   - no console.error in the happy path.
//
// The API is mocked (no network). DOM contract strings the implementation must produce:
//   unconfigured option text  = `${label} (not configured)`  and the <option> is disabled
//   removed current value     = an <option> whose text contains the id and "(removed)"
//   fetch-failure notice      = a field-help note whose text contains "manual"

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunLaunchForm } from "./RunLaunchForm";
import type { Param } from "../types";

vi.mock("../api", () => ({
  startRun: vi.fn(),
  fetchProviderOptions: vi.fn(),
  fetchVoices: vi.fn(),
}));

// Imported after the mock is registered; typed via vi.mocked below.
import { fetchProviderOptions, fetchVoices, startRun } from "../api";

const mockFetchOptions = vi.mocked(fetchProviderOptions);
const mockStartRun = vi.mocked(startRun);
const mockFetchVoices = vi.mocked(fetchVoices);

beforeEach(() => {
  // The form fetches the voice list on mount; every test needs it to resolve.
  mockFetchVoices.mockResolvedValue([
    { id: "", label: "Default voice", source: "preset" },
    { id: "preset:warm-female", label: "Warm female narrator", source: "preset" },
    { id: "preset:classic-male", label: "Classic male narrator", source: "preset" },
  ]);
});

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

function renderForm(param: Param, onStarted = vi.fn()) {
  render(
    <RunLaunchForm
      workflowId="wf"
      workflowName="WF"
      params={[param]}
      onStarted={onStarted}
      onCancel={() => {}}
    />,
  );
  return onStarted;
}

describe("RunLaunchForm options_from model select", () => {
  it("shows the label and submits the id", async () => {
    mockFetchOptions.mockResolvedValue([
      { id: "byteplus/seedance-2.5", label: "Seedance 2.5", configured: true, offered: true },
    ]);
    mockStartRun.mockResolvedValue({ run_id: "r1" });
    renderForm(modelParam());

    const option = await screen.findByRole("option", { name: "Seedance 2.5" });
    expect(option).toBeInTheDocument();
    expect(option).toHaveValue("byteplus/seedance-2.5");

    const select = screen.getByRole("combobox", { name: /Model/ });
    await userEvent.selectOptions(select, "byteplus/seedance-2.5");
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));

    await waitFor(() => {
      expect(mockStartRun).toHaveBeenCalled();
    });
    const body = mockStartRun.mock.calls[0][1] as { params: Record<string, unknown> };
    expect(body.params.model).toBe("byteplus/seedance-2.5");
  });

  it("requests the options for the param's source", async () => {
    mockFetchOptions.mockResolvedValue([]);
    renderForm(modelParam());
    await waitFor(() => {
      expect(mockFetchOptions).toHaveBeenCalledWith("sfvf.models:video");
    });
  });

  it("disables an unconfigured option and marks it with a suffix", async () => {
    mockFetchOptions.mockResolvedValue([
      { id: "google/veo-3.1-generate-001", label: "Veo 3.1", configured: false, offered: true },
    ]);
    renderForm(modelParam());

    const option = await screen.findByRole("option", { name: /Veo 3\.1.*not configured/i });
    expect(option).toBeDisabled();
  });

  it("shows a recorded value that is no longer offered, marked", async () => {
    mockFetchOptions.mockResolvedValue([
      { id: "byteplus/seedance-2.5", label: "Seedance 2.5", configured: true, offered: true },
    ]);
    renderForm(modelParam({ default: "legacy/removed-model" }));

    const option = await screen.findByRole("option", { name: /legacy\/removed-model.*removed/i });
    expect(option).toBeInTheDocument();
  });

  it("falls back to manual input with a notice when the options fetch fails", async () => {
    mockFetchOptions.mockRejectedValue(new Error("not found"));
    renderForm(modelParam());

    const input = await screen.findByRole("textbox", { name: /Model/ });
    expect(input).toBeInTheDocument();
    expect(screen.getByText(/manual/i)).toBeInTheDocument();
  });

  it("logs no console.error in the happy path", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockFetchOptions.mockResolvedValue([
      { id: "a/b", label: "Model AB", configured: true, offered: true },
    ]);
    renderForm(modelParam());

    await screen.findByRole("option", { name: "Model AB" });
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("renders fetched options as checkboxes for a multiselect", async () => {
    mockFetchOptions.mockResolvedValue([
      { id: "a/b", label: "Model AB", configured: true, offered: true },
    ]);
    renderForm(modelParam({ type: "multiselect" }));

    const checkbox = await screen.findByRole("checkbox", { name: /Model AB/ });
    expect(checkbox).toBeInTheDocument();
  });

  it("does not fetch options for a param without options_from", async () => {
    renderForm({ ...modelParam(), type: "text", options_from: null });
    // let any effects settle
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /Model/ })).toBeInTheDocument();
    });
    expect(mockFetchOptions).not.toHaveBeenCalled();
  });
});

// TASK-SSN-B1b: the run-settings controls (approval mode + per-video budget). The launch body
// carries gates_auto and per_video_budget (backend plumbed in B1a). The voice picker is deferred
// until B4 ships presets and a voices list to choose from.
describe("RunLaunchForm run settings", () => {
  function renderPlain(onStarted = vi.fn()) {
    render(
      <RunLaunchForm
        workflowId="wf"
        workflowName="WF"
        params={[]}
        onStarted={onStarted}
        onCancel={() => {}}
      />,
    );
    return onStarted;
  }

  it("defaults to manual approval and sends gates_auto=false with no budget", async () => {
    mockStartRun.mockResolvedValue({ run_id: "r1" });
    renderPlain();
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    const body = mockStartRun.mock.calls[0][1] as {
      gates_auto?: boolean;
      per_video_budget?: number | null;
    };
    expect(body.gates_auto).toBe(false);
    // No budget entered -> the cap is omitted (or null), never 0.
    expect(body.per_video_budget ?? null).toBeNull();
  });

  it("sends gates_auto=true when Autonomous is chosen and forwards a positive budget", async () => {
    mockStartRun.mockResolvedValue({ run_id: "r2" });
    renderPlain();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: /approval/i }),
      "autonomous",
    );
    await userEvent.type(screen.getByRole("spinbutton", { name: /budget/i }), "5");
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    const body = mockStartRun.mock.calls[0][1] as {
      gates_auto?: boolean;
      per_video_budget?: number;
    };
    expect(body.gates_auto).toBe(true);
    expect(body.per_video_budget).toBe(5);
  });

  it("blocks submit with an error when the per-video budget is not positive", async () => {
    mockStartRun.mockResolvedValue({ run_id: "r3" });
    renderPlain();
    await userEvent.type(screen.getByRole("spinbutton", { name: /budget/i }), "0");
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));
    expect(await screen.findByText(/greater than 0/i)).toBeInTheDocument();
    expect(mockStartRun).not.toHaveBeenCalled();
  });
});

// TASK-SSN-B4b: the voice picker. The form fetches the voice list (bundled presets + owner voice
// assets) and sends the chosen `voice` id in the launch body ("" = default; "preset:<stem>" or an
// owner asset id otherwise). B4a's resolver interprets the id server-side.
describe("RunLaunchForm voice picker", () => {
  function renderPlain(onStarted = vi.fn()) {
    render(
      <RunLaunchForm
        workflowId="wf"
        workflowName="WF"
        params={[]}
        onStarted={onStarted}
        onCancel={() => {}}
      />,
    );
    return onStarted;
  }

  it("renders the fetched voices and defaults to the default voice", async () => {
    mockStartRun.mockResolvedValue({ run_id: "v1" });
    renderPlain();
    // options from fetchVoices are present
    expect(await screen.findByRole("option", { name: /warm female narrator/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /classic male narrator/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    const body = mockStartRun.mock.calls[0][1] as { voice?: string };
    expect(body.voice ?? "").toBe(""); // default selection -> the default voice
  });

  it("sends the chosen voice id in the launch body", async () => {
    mockStartRun.mockResolvedValue({ run_id: "v2" });
    renderPlain();
    const select = await screen.findByRole("combobox", { name: /voice/i });
    await userEvent.selectOptions(select, "preset:warm-female");
    await userEvent.click(screen.getByRole("button", { name: /start run/i }));
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    const body = mockStartRun.mock.calls[0][1] as { voice?: string };
    expect(body.voice).toBe("preset:warm-female");
  });

  it("falls back gracefully and still launches when the voice list fails to load", async () => {
    mockFetchVoices.mockRejectedValue(new Error("network down"));
    mockStartRun.mockResolvedValue({ run_id: "v3" });
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    renderPlain();
    // the form is still usable: Start run works and sends the default voice
    await userEvent.click(await screen.findByRole("button", { name: /start run/i }));
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    const body = mockStartRun.mock.calls[0][1] as { voice?: string };
    expect(body.voice ?? "").toBe("");
    expect(errorSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
  });
});
