// Frozen contract - F3-6b: run-form chassis controls (PRD §8.2).
//
//   R-028 Dry run       - checkbox labelled "Dry run"; checked -> body.dry_run === true;
//                         unchecked -> dry_run false or omitted.
//   R-027 Parallel steps - integer field labelled "Parallel steps per video", seeded from the Settings
//                         default (settings.defaults.default_step_concurrency.effective);
//                         body.step_concurrency carries it; < 1 / non-integer blocks submit.
//   R-023 Max videos    - RunLaunchForm prop `maxVideos` (number | null): the "Video count" input gets
//                         max=<n>; a count above it blocks submit with an error naming the cap.
//                         WorkflowCard passes `workflow.max_videos` through.
//   R-021 Decimal point - a "number" param renders as a text input with inputMode="decimal";
//                         "1.5" submits 1.5 whatever the OS locale; "1,5" blocks submit with an error
//                         that mentions a (decimal) point.
//   R-030 Remembered    - after a SUCCESSFUL start, the submitted values are stored in localStorage
//                         under `sfvf.launchForm.<workflowId>` (JSON) and pre-fill the form the next
//                         time it opens for that workflow (params, video count, concurrency, parallel
//                         steps, approval mode, voice, dry run). They win over the Settings-seeded
//                         defaults. Another workflow is unaffected. Unreadable/corrupt storage, or a
//                         storage that throws, falls back to the defaults without crashing.
//   R-019 Last-known options - each successful `options_from` fetch is stored under
//                         `sfvf.providerOptions.<source>`; when a later fetch fails and a stored list
//                         exists, the select is still offered from it together with a warning whose
//                         text contains "last known". With no stored list the existing manual-input
//                         fallback (P-9b) is unchanged.
//
// Supervisor-authored, RED-first. The API is mocked (no network).

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunLaunchForm } from "./RunLaunchForm";
import { WorkflowCard } from "./WorkflowCard";
import type { Param, Workflow } from "../types";

vi.mock("../api", () => ({
  startRun: vi.fn(),
  fetchProviderOptions: vi.fn(),
  fetchVoices: vi.fn(),
  fetchSettings: vi.fn(),
  fetchEstimate: vi.fn(),
}));

import { fetchEstimate, fetchProviderOptions, fetchSettings, fetchVoices, startRun } from "../api";

const mockFetchOptions = vi.mocked(fetchProviderOptions);
const mockStartRun = vi.mocked(startRun);
const mockFetchVoices = vi.mocked(fetchVoices);
const mockFetchSettings = vi.mocked(fetchSettings);
const mockFetchEstimate = vi.mocked(fetchEstimate);

type Body = {
  params: Record<string, unknown>;
  video_count: number;
  concurrency: number;
  gates_auto?: boolean;
  voice?: string;
  dry_run?: boolean;
  step_concurrency?: number;
};

function settings(defaultConcurrency = 1, defaultStepConcurrency = 1) {
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

function param(overrides: Partial<Param>): Param {
  return {
    key: "p",
    type: "text",
    label: "P",
    required: false,
    default: null,
    help: null,
    affects_cost: false,
    min: null,
    max: null,
    step: null,
    options: null,
    options_from: null,
    placeholder: null,
    unit: null,
    ...overrides,
  };
}

function renderForm(
  opts: { workflowId?: string; params?: Param[]; maxVideos?: number | null } = {},
) {
  return render(
    <RunLaunchForm
      workflowId={opts.workflowId ?? "wf"}
      workflowName="WF"
      params={opts.params ?? []}
      maxVideos={opts.maxVideos ?? null}
      onStarted={vi.fn()}
      onCancel={() => {}}
    />,
  );
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: /start run/i }));
}

function lastBody(): Body {
  const call = mockStartRun.mock.calls.at(-1);
  if (!call) {
    throw new Error("startRun was not called");
  }
  return call[1] as Body;
}

async function setField(label: RegExp, text: string) {
  const el = screen.getByLabelText(label);
  await userEvent.clear(el);
  if (text !== "") {
    await userEvent.type(el, text);
  }
}

beforeEach(() => {
  window.localStorage.clear();
  mockFetchVoices.mockResolvedValue([
    { id: "", label: "Default voice", source: "preset" },
    { id: "preset:warm-female", label: "Warm female narrator", source: "preset" },
  ]);
  mockFetchSettings.mockResolvedValue(settings() as never);
  mockFetchEstimate.mockResolvedValue({
    per_meter: {},
    confidence: "none",
    matches: 0,
    video_count: 1,
  } as never);
  mockFetchOptions.mockResolvedValue([]);
  mockStartRun.mockResolvedValue({ run_id: "r1" });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  window.localStorage.clear();
});

// ------------------------------------------------------------------ R-028 dry run

describe("dry run (R-028)", () => {
  it("is off by default and not sent as true", async () => {
    renderForm();
    expect(screen.getByRole("checkbox", { name: /dry run/i })).not.toBeChecked();
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().dry_run ?? false).toBe(false);
  });

  it("sends dry_run=true when ticked", async () => {
    renderForm();
    await userEvent.click(screen.getByRole("checkbox", { name: /dry run/i }));
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().dry_run).toBe(true);
  });
});

// ------------------------------------------------------------------ R-027 parallel steps

describe("parallel steps per video (R-027)", () => {
  it("is seeded from the Settings default and sent as step_concurrency", async () => {
    mockFetchSettings.mockResolvedValue(settings(1, 3) as never);
    renderForm();
    await waitFor(() => expect(screen.getByLabelText(/parallel steps/i)).toHaveValue(3));
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().step_concurrency).toBe(3);
  });

  it("sends the value the user enters", async () => {
    renderForm();
    await setField(/parallel steps/i, "2");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().step_concurrency).toBe(2);
  });

  it("blocks submit when it is below 1", async () => {
    renderForm();
    await setField(/parallel steps/i, "0");
    await submit();
    expect(await screen.findByText(/parallel steps/i, { selector: ".form-error" })).toBeInTheDocument();
    expect(mockStartRun).not.toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------ R-023 max videos

describe("max videos cap (R-023)", () => {
  it("caps the video-count input at the workflow's maximum", () => {
    renderForm({ maxVideos: 3 });
    expect(screen.getByLabelText(/video count/i)).toHaveAttribute("max", "3");
  });

  it("blocks submit above the cap with an error naming it", async () => {
    renderForm({ maxVideos: 3 });
    await setField(/video count/i, "4");
    await submit();
    const error = await screen.findByText(/3/, { selector: ".form-error" });
    expect(error).toBeInTheDocument();
    expect(mockStartRun).not.toHaveBeenCalled();
  });

  it("allows exactly the cap", async () => {
    renderForm({ maxVideos: 3 });
    await setField(/video count/i, "3");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().video_count).toBe(3);
  });

  it("has no max when the workflow declares none", () => {
    renderForm({ maxVideos: null });
    expect(screen.getByLabelText(/video count/i)).not.toHaveAttribute("max");
  });

  it("WorkflowCard passes workflow.max_videos to the form", async () => {
    const workflow = {
      id: "capped",
      name: "Capped",
      description: null,
      thumbnail_url: null,
      valid: true,
      problems: [],
      quality_factors: [],
      params: [],
      avg_cost_per_meter: {},
      runs_counted: 0,
      archived: false,
      last_run: null,
      max_videos: 2,
    } as Workflow;
    render(
      <WorkflowCard workflow={workflow} seen={false} onStarted={vi.fn()} onViewRuns={vi.fn()} />,
    );
    await userEvent.click(screen.getByRole("button", { name: /run workflow/i }));
    expect(await screen.findByLabelText(/video count/i)).toHaveAttribute("max", "2");
  });
});

// ------------------------------------------------------------------ R-021 decimal point

describe("decimal point regardless of locale (R-021)", () => {
  const ratio = param({ key: "ratio", label: "Ratio", type: "number", default: 0.5 });

  it("renders a number param as a decimal text input", () => {
    renderForm({ params: [ratio] });
    const input = screen.getByLabelText(/ratio/i);
    expect(input).toHaveAttribute("inputmode", "decimal");
    expect(input).toHaveValue("0.5");
  });

  it("submits a point decimal as a number", async () => {
    renderForm({ params: [ratio] });
    await setField(/ratio/i, "1.5");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().params.ratio).toBe(1.5);
  });

  it("rejects a comma decimal with a message about the point", async () => {
    renderForm({ params: [ratio] });
    await setField(/ratio/i, "1,5");
    await submit();
    expect(await screen.findByText(/point/i, { selector: ".form-error" })).toBeInTheDocument();
    expect(mockStartRun).not.toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------ R-030 remembered values

describe("last-used values are remembered per workflow (R-030)", () => {
  const topic = param({ key: "topic", label: "Topic", type: "text" });

  it("pre-fills the form with the values of the last successful start", async () => {
    renderForm({ params: [topic] });
    await setField(/video count/i, "2");
    await setField(/^topic/i, "cats");
    await userEvent.click(screen.getByRole("checkbox", { name: /dry run/i }));
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    cleanup();

    renderForm({ params: [topic] });
    expect(screen.getByLabelText(/video count/i)).toHaveValue(2);
    expect(screen.getByLabelText(/^topic/i)).toHaveValue("cats");
    expect(screen.getByRole("checkbox", { name: /dry run/i })).toBeChecked();
  });

  it("keeps remembered concurrency over the Settings default", async () => {
    window.localStorage.setItem(
      "sfvf.launchForm.wf",
      JSON.stringify({ video_count: 1, concurrency: 4, params: {} }),
    );
    mockFetchSettings.mockResolvedValue(settings(1, 1) as never);
    renderForm();
    await waitFor(() => expect(mockFetchSettings).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByLabelText(/^concurrency/i)).toHaveValue(4);
  });

  it("does not leak into another workflow", async () => {
    renderForm({ params: [topic] });
    await setField(/^topic/i, "cats");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    cleanup();

    renderForm({ workflowId: "other", params: [topic] });
    expect(screen.getByLabelText(/^topic/i)).toHaveValue("");
  });

  it("does not remember a start that failed", async () => {
    mockStartRun.mockResolvedValue({ error: "nope" } as never);
    renderForm({ params: [topic] });
    await setField(/^topic/i, "cats");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    cleanup();

    renderForm({ params: [topic] });
    expect(screen.getByLabelText(/^topic/i)).toHaveValue("");
  });

  it("falls back to defaults when the stored value is corrupt", () => {
    window.localStorage.setItem("sfvf.launchForm.wf", "{not json");
    renderForm({ params: [topic] });
    expect(screen.getByLabelText(/video count/i)).toHaveValue(1);
    expect(screen.getByLabelText(/^topic/i)).toHaveValue("");
  });

  it("still works when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderForm({ params: [topic] });
    expect(screen.getByLabelText(/video count/i)).toHaveValue(1);
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
  });
});

// ------------------------------------------------------------------ R-019 last-known options

describe("last-known option list when the options fetch fails (R-019)", () => {
  const model = param({
    key: "model",
    type: "select",
    label: "Model",
    options_from: "sfvf.models:video",
  });

  it("offers the last fetched list with a warning when a later fetch fails", async () => {
    mockFetchOptions.mockResolvedValueOnce([
      { id: "byteplus/seedance-2.5", label: "Seedance 2.5", configured: true, offered: true },
    ]);
    renderForm({ params: [model] });
    await screen.findByRole("option", { name: "Seedance 2.5" });
    cleanup();

    mockFetchOptions.mockRejectedValueOnce(new Error("offline"));
    renderForm({ params: [model] });
    expect(await screen.findByRole("option", { name: "Seedance 2.5" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: /model/i })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/last known/i);
  });

  it("keeps the manual fallback when nothing was ever fetched", async () => {
    mockFetchOptions.mockRejectedValueOnce(new Error("offline"));
    renderForm({ params: [model] });
    expect(await screen.findByRole("textbox", { name: /model/i })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/manual/i);
  });
});
