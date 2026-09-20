// Registers @testing-library/jest-dom matchers (toBeInTheDocument, toBeDisabled, …) on vitest's
// `expect`, and augments vitest's Assertion types so they type-check. Loaded via
// `test.setupFiles` in vite.config.ts before every test file.
import "@testing-library/jest-dom/vitest";
