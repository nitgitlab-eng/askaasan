import { describe, expect, it } from "vitest";

import { diff } from "./vision";

describe("change detection", () => {
  it("is zero for identical frames and large for different ones", () => {
    const a = new Uint8ClampedArray(768).fill(100);
    const b = new Uint8ClampedArray(768).fill(100);
    expect(diff(a, b)).toBe(0);
    b.fill(140, 0, 384); // half the page changed by 40 levels
    expect(diff(a, b)).toBe(20);
  });
  it("treats a missing reference as maximally different, so the first stable view is sent", () => {
    expect(diff(new Uint8ClampedArray(4), null)).toBe(255);
  });
});
