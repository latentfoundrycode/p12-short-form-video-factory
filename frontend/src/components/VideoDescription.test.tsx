// Frozen contract — TASK-SSN-B5: the per-video description is surfaced READ-ONLY in the run view.
//
// A workflow's Result.description (e.g. the video's sources) rides into VideoRecord.result.description
// (the runner emits it in the result event, which the supervisor captures verbatim). The run view
// shows it read-only per video via a small `VideoDescription` component: the text plus a label when a
// non-empty description is present, and nothing at all otherwise (no crash, no "undefined").

import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VideoDescription } from "./RunRecordView";
import type { VideoRecord } from "../types";

function video(overrides: Partial<VideoRecord> = {}): VideoRecord {
  return {
    index: 1,
    status: "complete",
    started_utc: "2026-09-26T00:00:00Z",
    ended_utc: "2026-09-26T00:01:00Z",
    ...overrides,
  };
}

let errorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
});

describe("VideoDescription", () => {
  it("shows the description text and an index-labelled header when present", () => {
    render(
      <VideoDescription
        video={video({ index: 2, result: { description: "Sources: example.com" } })}
      />,
    );
    expect(screen.getByText(/Sources: example\.com/)).toBeTruthy();
    // The header labels the section and carries the per-video index, matching the sibling panels.
    expect(screen.getByText(/description.*#\s*2/i)).toBeTruthy();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("renders nothing when the description is empty", () => {
    const { container } = render(<VideoDescription video={video({ result: { description: "" } })} />);
    expect(container.textContent).toBe("");
    expect(errorSpy).not.toHaveBeenCalled();
  });

  it("renders nothing when there is no result", () => {
    const { container } = render(<VideoDescription video={video({ result: null })} />);
    expect(container.textContent).toBe("");
    expect(container.textContent).not.toContain("undefined");
    expect(errorSpy).not.toHaveBeenCalled();
  });
});
