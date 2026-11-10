import { describe, expect, it } from "vitest";

import { LAB_SECTION, SECTIONS, sectionFor, tabFor, visibleTabs } from "./nav";

const key = (p: string) => sectionFor(p)?.key;

describe("navigation sections", () => {
  it("every route maps to its section, nested routes included", () => {
    expect(key("/")).toBe("home");
    expect(key("/today")).toBe("home");
    expect(key("/learn/5/lesson/9")).toBe("learn");
    expect(key("/paths/data-analyst")).toBe("learn");
    expect(key("/mastery/3")).toBe("progress");
    expect(key("/roleplay/12")).toBe("practice");
    expect(key("/certificates")).toBe("certificates");
    expect(key("/connect")).toBe("lab");
    expect(key("/account")).toBeUndefined(); // lives in the You menu
    expect(key("/learnings")).toBeUndefined(); // a prefix of a word is not a match
  });

  it("finds the right tab", () => {
    const learn = SECTIONS.find((s) => s.key === "learn")!;
    expect(tabFor("/learn/5", learn)?.to).toBe("/learn");
    expect(tabFor("/catalog", learn)?.to).toBe("/catalog");
    expect(tabFor("/lab/7", LAB_SECTION)?.to).toBe("/lab");
  });

  it("switched-off features hide only their tabs", () => {
    const practice = SECTIONS.find((s) => s.key === "practice")!;
    expect(visibleTabs(practice, ["mentor", "live"]).map((t) => t.to)).toEqual(["/roleplay", "/workshops"]);
    expect(visibleTabs(practice, ["mentor", "roleplay", "live", "workshops"])).toEqual([]);
  });

  it("no route is listed twice", () => {
    const all = [...SECTIONS, LAB_SECTION].flatMap((s) => s.tabs.map((t) => t.to));
    expect(new Set(all).size).toBe(all.length);
  });
});
