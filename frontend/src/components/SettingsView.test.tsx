// Frozen contract - Settings tab F1c: the SettingsView (R-066 UI + R-068 UI).
//
// SettingsView replaces the placeholder settings tab (PRD 8.7, mockup screen "Settings"). It
// fetches api.fetchSettings() on mount and renders:
//   - "API keys": a row per allowed secret name showing configured/missing; a write-only input to
//     set/replace a key (api.putSecret) and, when configured, a Clear control (api.deleteSecret).
//     A stored value is NEVER shown (the API never returns one).
//   - "Connections": a genuine empty state (no MCP-based provider to sign into).
//   - "Global defaults": the four 8.7 defaults (effective value + source), editable and persisted
//     via api.putDefaults.
//   - error: a load failure with a Retry control that refetches.
// Observability: no console.error across any state; nothing rendered as undefined/NaN/[object Object].
//
// Accessible hooks the implementation must expose (this is the frozen contract):
//   - the value input for a secret has accessible name "Set <NAME>"
//   - the save button for a secret has accessible name "Save <NAME>"
//   - the clear button for a configured secret has accessible name "Clear <NAME>"
//   - the default fields have labels "Step silence limit (seconds)", "Default concurrency",
//     "Default step concurrency", "Max cache size (bytes)"; a button named /save.*default/i persists.
//   - the error state renders a button named /retry/i.
//
// API mocked (no network). Supervisor-authored frozen contract (RED-first); the builder implements
// SettingsView.tsx + the api helpers.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsView } from "./SettingsView";

vi.mock("../api", () => ({
  fetchSettings: vi.fn(),
  putSecret: vi.fn(),
  deleteSecret: vi.fn(),
  putDefaults: vi.fn(),
}));

import { deleteSecret, fetchSettings, putDefaults, putSecret } from "../api";

const mockFetch = vi.mocked(fetchSettings);
const mockPut = vi.mocked(putSecret);
const mockDelete = vi.mocked(deleteSecret);
const mockPutDefaults = vi.mocked(putDefaults);

let errorSpy: ReturnType<typeof vi.spyOn>;

type SettingsPayload = ReturnType<typeof settingsPayload>;

function settingsPayload(overrides: Record<string, unknown> = {}) {
  return {
    providers: [
      {
        id: "openrouter",
        label: "OpenRouter",
        secret_names: ["OPENROUTER_API_KEY"],
        configured: false,
      },
      {
        id: "google",
        label: "Google (Agent Platform / Vertex)",
        secret_names: ["GOOGLE_SA_JSON"],
        configured: true,
      },
    ],
    configured_secret_names: ["GOOGLE_SA_JSON"],
    allowed_secret_names: ["OPENROUTER_API_KEY", "GOOGLE_SA_JSON"],
    defaults: {
      silence_limit_seconds: { effective: 300, source: "default" },
      default_concurrency: { effective: 1, source: "default" },
      default_step_concurrency: { effective: 1, source: "default" },
      cache_max_bytes: { effective: 5368709120, source: "default" },
    },
    ...overrides,
  };
}

beforeEach(() => {
  errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
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

describe("SettingsView", () => {
  it("loaded: renders provider key rows and the global defaults", async () => {
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    render(<SettingsView />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    await screen.findByText("OpenRouter");
    screen.getByText("Google (Agent Platform / Vertex)");
    // the four defaults are surfaced (label present)
    screen.getByLabelText("Step silence limit (seconds)");
    screen.getByLabelText("Max cache size (bytes)");
    noPlaceholders();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("never displays a stored secret value", async () => {
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    // the payload carries no values; the view must not invent one or echo the name as a value
    const inputs = screen.getAllByLabelText(/^Set /);
    for (const input of inputs) {
      expect((input as HTMLInputElement).value).toBe("");
    }
  });

  it("set a key: calls putSecret and refetches", async () => {
    const user = userEvent.setup();
    mockFetch
      .mockResolvedValueOnce(settingsPayload() as SettingsPayload)
      .mockResolvedValueOnce(
        settingsPayload({
          configured_secret_names: ["OPENROUTER_API_KEY", "GOOGLE_SA_JSON"],
        }) as SettingsPayload,
      );
    mockPut.mockResolvedValue(undefined);
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    await user.type(screen.getByLabelText("Set OPENROUTER_API_KEY"), "sk-new-key");
    await user.click(screen.getByRole("button", { name: "Save OPENROUTER_API_KEY" }));
    await waitFor(() => expect(mockPut).toHaveBeenCalledWith("OPENROUTER_API_KEY", "sk-new-key"));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
  });

  it("clear a configured key: calls deleteSecret", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    mockDelete.mockResolvedValue(undefined);
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    await user.click(screen.getByRole("button", { name: "Clear GOOGLE_SA_JSON" }));
    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("GOOGLE_SA_JSON"));
  });

  it("save defaults: calls putDefaults with the edited field", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    mockPutDefaults.mockResolvedValue(undefined);
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    const silence = screen.getByLabelText("Step silence limit (seconds)");
    await user.clear(silence);
    await user.type(silence, "120");
    await user.click(screen.getByRole("button", { name: /save.*default/i }));
    await waitFor(() =>
      expect(mockPutDefaults).toHaveBeenCalledWith(
        expect.objectContaining({ silence_limit_seconds: 120 }),
      ),
    );
  });

  it("error: shows a failure with Retry that refetches", async () => {
    const user = userEvent.setup();
    mockFetch
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(settingsPayload() as SettingsPayload);
    render(<SettingsView />);
    await user.click(await screen.findByRole("button", { name: /retry/i }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    await screen.findByText("OpenRouter");
    noPlaceholders();
  });

  it("a failed save surfaces an error instead of swallowing it", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    mockPut.mockRejectedValue(new Error("secret store is locked"));
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    await user.type(screen.getByLabelText("Set OPENROUTER_API_KEY"), "sk-x");
    await user.click(screen.getByRole("button", { name: "Save OPENROUTER_API_KEY" }));
    // the failure is shown to the user, not silently dropped
    await screen.findByText(/lock|could|fail|error/i);
  });

  it("disables Save for a key until a value is entered", async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(settingsPayload() as SettingsPayload);
    render(<SettingsView />);
    await screen.findByText("OpenRouter");
    const save = screen.getByRole("button", { name: "Save OPENROUTER_API_KEY" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Set OPENROUTER_API_KEY"), "k");
    expect((save as HTMLButtonElement).disabled).toBe(false);
  });
});
