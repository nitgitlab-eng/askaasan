import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { CategorizationBody, MatchingBody } from "./bodies";

// Own file: React reports a missing-key warning only once per component per module, so it must be the first render.
it("matching renders keyed rows (no React key warning)", () => {
  const err = vi.spyOn(console, "error").mockImplementation(() => {});
  const payload = { left: [{ id: "l0", text: "Data" }, { id: "l1", text: "Model" }], right: [{ id: "r0", text: "Examples" }, { id: "r1", text: "Pattern" }] };
  render(<MatchingBody payload={payload} answer={{}} setAnswer={vi.fn()} result={null} locked={false} />);
  expect(err.mock.calls.some((c) => String(c[0]).includes("key"))).toBe(false);
  err.mockRestore();
});

it("categorization buckets don't nest buttons, and placed chips can be re-picked", () => {
  const set = vi.fn();
  const { container } = render(
    <CategorizationBody payload={{ categories: ["AI", "Not AI"], items: [{ id: "c0", text: "Spam filter" }, { id: "c1", text: "Torch" }] }} answer={{ assign: { c0: "AI" } }} setAnswer={set} result={null} locked={false} />,
  );
  expect(container.querySelector("button button")).toBeNull();
  fireEvent.click(screen.getByText("Spam filter")); // pick the placed chip (must not re-place it into its own bucket)
  expect(set).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Not AI" }));
  expect(set).toHaveBeenCalledWith({ assign: { c0: "Not AI" } });
});
