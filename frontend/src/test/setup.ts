// Shared vitest setup (test.setupFiles in vite.config.ts), run before every test file.
// - registers @testing-library/jest-dom matchers on vitest's `expect` (+ their types);
// - unmounts React trees after each test so renders don't accumulate in the jsdom document
//   (needed because we use explicit vitest imports, not globals, so RTL's own auto-cleanup —
//   which hooks a global afterEach — is not registered).
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
});
