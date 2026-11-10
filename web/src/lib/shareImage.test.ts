import { describe, expect, it } from "vitest";

import { composePost } from "./credentials";
import { esc, shareSvg, wrap } from "./shareImage";

describe("share image", () => {
  it("escapes user text so a course title can't inject SVG", () => {
    const svg = shareSvg({ eyebrow: "CERTIFICATE", title: '<script>alert(1)</script> & "Excel"', lines: ["<img src=x onerror=alert(1)>"], footer: "aasan.in/verify/abc" });
    expect(svg).not.toContain("<script>");
    expect(svg).not.toContain("<img");
    expect(svg).toContain("&lt;script&gt;");
    expect(new DOMParser().parseFromString(svg, "image/svg+xml").querySelector("parsererror")).toBeNull();
  });
  it("drops control characters", () => {
    expect(esc("a\u0001b")).toBe("ab");
  });
  it("wraps and truncates", () => {
    expect(wrap("one two three four", 9, 3)).toEqual(["one two", "three", "four"]);
    expect(wrap("aaaa bbbb cccc dddd", 4, 2)).toEqual(["aaaa", "bbb…"]);
    expect(wrap("supercalifragilistic", 6, 1)).toEqual(["super…"]);
  });
});

describe("composePost", () => {
  it("appends clean hashtags", () => {
    expect(composePost(" Hello ", ["Learning", "#Excel", "bad tag!"])).toBe("Hello\n\n#Learning #Excel #badtag");
    expect(composePost("Plain", [])).toBe("Plain");
  });
});
