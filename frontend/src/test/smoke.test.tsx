// Toolchain smoke test — proves vitest + jsdom + @testing-library/react + jest-dom matchers are
// wired and that `npm run test` (and the CI gate) execute frontend unit tests. Real component
// tests (the §3.7 RunLaunchForm assertions) arrive in P-9b.
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("frontend test toolchain", () => {
  it("renders a component into jsdom and asserts with jest-dom", () => {
    render(<p>toolchain online</p>);
    expect(screen.getByText("toolchain online")).toBeInTheDocument();
  });
});
