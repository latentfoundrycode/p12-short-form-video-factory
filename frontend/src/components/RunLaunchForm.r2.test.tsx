// Frozen contract - TASK-102 r2: review follow-ups on the launch form (R-028, R-030).
//
//   1. Design: the Dry run checkbox uses the same `field-check` label pattern as every other
//      checkbox (never `field field-check` on one element) and carries a help line about fake
//      assets / no spending.
//   2. Review A: a manual-input multiselect (no options, no options_from) is restored from the
//      remembered values as its comma-separated text.
//   3. Review B: a remembered decimal round-trips: what the form accepted is shown again in a form
//      it accepts (never scientific notation such as "1e-7").
//   4. Review B: a remembered voice is applied only once the loaded voice list confirms it; a
//      submit before the list settles sends the default voice "".
//
// Supervisor-authored, RED-first. The API is mocked (no network).

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RunLaunchForm } from "./RunLaunchForm";
import type { Param, Voice } from "../types";

vi.mock("../api", () => ({
  startRun: vi.fn(),
  fetchProviderOptions: vi.fn(),
  fetchVoices: vi.fn(),
  fetchSettings: vi.fn(),
  fetchEstimate: vi.fn(),
}));

import { fetchEstimate, fetchSettings, fetchVoices, startRun } from "../api";

const mockStartRun = vi.mocked(startRun);
const mockFetchVoices = vi.mocked(fetchVoices);

const VOICES: Voice[] = [
  { id: "", label: "Default voice", source: "preset" },
  { id: "preset:warm-female", label: "Warm female narrator", source: "preset" },
] as Voice[];

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

function renderForm(params: Param[] = []) {
  return render(
    <RunLaunchForm
      workflowId="wf"
      workflowName="WF"
      params={params}
      maxVideos={null}
      onStarted={vi.fn()}
      onCancel={() => {}}
    />,
  );
}

function lastBody(): { params: Record<string, unknown>; voice?: string } {
  const call = mockStartRun.mock.calls.at(-1);
  if (!call) {
    throw new Error("startRun was not called");
  }
  return call[1] as { params: Record<string, unknown>; voice?: string };
}

async function submit() {
  await userEvent.click(screen.getByRole("button", { name: /start run/i }));
}

beforeEach(() => {
  mockFetchVoices.mockResolvedValue(VOICES);
  vi.mocked(fetchSettings).mockResolvedValue({
    providers: [],
    configured_secret_names: [],
    allowed_secret_names: [],
    defaults: {
      silence_limit_seconds: { effective: 300, source: "default" },
      default_concurrency: { effective: 1, source: "default" },
      default_step_concurrency: { effective: 1, source: "default" },
      cache_max_bytes: { effective: 5368709120, source: "default" },
    },
  } as never);
  vi.mocked(fetchEstimate).mockResolvedValue({
    per_meter: {},
    confidence: "none",
    matches: 0,
    video_count: 1,
  } as never);
  mockStartRun.mockResolvedValue({ run_id: "r1" });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("Dry run control (design follow-up, R-028)", () => {
  it("uses the shared field-check label pattern", () => {
    renderForm();
    const label = screen.getByRole("checkbox", { name: /dry run/i }).closest("label");
    expect(label).not.toBeNull();
    expect(label).toHaveClass("field-check");
    expect(label).not.toHaveClass("field");
  });

  it("explains itself with a help line", () => {
    renderForm();
    expect(screen.getByText(/fake assets/i)).toBeInTheDocument();
  });
});

describe("manual-input multiselect is remembered (R-030)", () => {
  it("restores the comma-separated text", async () => {
    const tags = param({ key: "tags", label: "Tags", type: "multiselect" });
    renderForm([tags]);
    await userEvent.type(screen.getByLabelText(/^tags/i), "space, mars");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().params.tags).toEqual(["space", "mars"]);
    cleanup();

    renderForm([tags]);
    expect(screen.getByLabelText(/^tags/i)).toHaveValue("space, mars");
  });
});

describe("remembered decimals round-trip (R-021/R-030)", () => {
  it("never shows a remembered decimal in scientific notation", async () => {
    const ratio = param({ key: "ratio", label: "Ratio", type: "number" });
    renderForm([ratio]);
    await userEvent.type(screen.getByLabelText(/^ratio/i), "0.0000001");
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(1));
    expect(lastBody().params.ratio).toBe(0.0000001);
    cleanup();

    renderForm([ratio]);
    const shown = (screen.getByLabelText(/^ratio/i) as HTMLInputElement).value;
    expect(shown).not.toMatch(/e/i);
    expect(Number(shown)).toBe(0.0000001);
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(2));
    expect(lastBody().params.ratio).toBe(0.0000001);
  });
});

describe("remembered decimals round-trip at both magnitude extremes (r2 assumption 1)", () => {
  it.each([
    ["1000000000000000000000", 1e21],
    ["-0.00000025", -2.5e-7],
    ["123456789012345680000000", 1.2345678901234568e23],
  ])("restores %s without an exponent", async (typed, value) => {
    const ratio = param({ key: "ratio", label: "Ratio", type: "number" });
    renderForm([ratio]);
    await userEvent.type(screen.getByLabelText(/^ratio/i), typed);
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(1));
    expect(lastBody().params.ratio).toBe(value);
    cleanup();

    renderForm([ratio]);
    const shown = (screen.getByLabelText(/^ratio/i) as HTMLInputElement).value;
    expect(shown).not.toMatch(/e/i);
    expect(Number(shown)).toBe(value);
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalledTimes(2));
    expect(lastBody().params.ratio).toBe(value);
  });
});

describe("remembered voice waits for the voice list (R-030)", () => {
  it("sends the default voice when submitted before the list settles", async () => {
    window.localStorage.setItem(
      "sfvf.launchForm.wf",
      JSON.stringify({ video_count: 1, concurrency: 1, params: {}, voice: "preset:warm-female" }),
    );
    let resolveVoices: (value: Voice[]) => void = () => {};
    mockFetchVoices.mockReturnValue(
      new Promise<Voice[]>((resolve) => {
        resolveVoices = resolve;
      }),
    );
    renderForm();
    await submit();
    await waitFor(() => expect(mockStartRun).toHaveBeenCalled());
    expect(lastBody().voice ?? "").toBe("");

    await act(async () => {
      resolveVoices(VOICES);
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.getByRole("combobox", { name: /voice/i })).toHaveValue("preset:warm-female");
  });
});
