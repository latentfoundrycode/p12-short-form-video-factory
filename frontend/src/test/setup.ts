// Shared vitest setup (test.setupFiles in vite.config.ts), run before every test file.
// - registers @testing-library/jest-dom matchers on vitest's `expect` (+ their types);
// - unmounts React trees after each test so renders don't accumulate in the jsdom document
//   (needed because we use explicit vitest imports, not globals, so RTL's own auto-cleanup —
//   which hooks a global afterEach — is not registered);
// - clears localStorage after each test, because one jsdom environment is shared by all tests in a
//   file and the launch form remembers values there (TASK-102, R-019/R-030) — without this a value
//   remembered by one test would pre-fill the next.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
  try {
    window.localStorage.clear();
  } catch {
    // a test may have stubbed Storage to throw; nothing to clear then
  }
});
