import { render, screen } from "@testing-library/react";
import { useRef } from "react";
import { expect, it, vi } from "vitest";

import { useFillViewport } from "./useFillViewport";

function Page() {
  const ref = useRef<HTMLDivElement>(null);
  const h = useFillViewport(ref);
  return <div ref={ref} data-testid="page" style={{ height: h }} />;
}

it("fills the screen from where the page starts, so the bottom (Ask Aasan's message box) stays visible", () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ top: 150 } as DOMRect); // top bar + banner
  Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
  render(<Page />);
  expect(screen.getByTestId("page").style.height).toBe("750px");
  vi.restoreAllMocks();
});
