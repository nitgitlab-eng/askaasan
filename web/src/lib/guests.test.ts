import { describe, expect, it } from "vitest";

import { expiryFromDays, guestToken, parseProspects, splitCsvLine, validSlug } from "./guests";

describe("parseProspects", () => {
  it("skips the header, bad lines and duplicate emails", () => {
    const r = parseProspects("company,email,industry\nSwift Logistics, OPS@swift.in ,logistics\nbad line\nSwift again,ops@swift.in\n\n\"Rao, Sons\",rao@x.in");
    expect(r.rows).toEqual([
      { company: "Swift Logistics", email: "ops@swift.in", industry: "logistics" },
      { company: "Rao, Sons", email: "rao@x.in", industry: "" },
    ]);
    expect(r.bad).toBe(1);
  });
});

describe("splitCsvLine", () => {
  it("handles quotes and escaped quotes", () => {
    expect(splitCsvLine('a,"b, c","d ""e"""')).toEqual(["a", "b, c", 'd "e"']);
  });
});

describe("helpers", () => {
  it("validates slugs like the server", () => {
    expect(validSlug("open-day")).toBe(true);
    expect(validSlug("Open Day")).toBe(false);
    expect(validSlug("-bad")).toBe(false);
    expect(validSlug("ab")).toBe(false);
  });
  it("computes expiry", () => {
    expect(expiryFromDays(null)).toBeNull();
    expect(expiryFromDays(2, new Date("2026-01-01T00:00:00Z"))).toBe("2026-01-03T00:00:00.000Z");
  });
  it("stores guest tokens per slug", () => {
    guestToken.set("a-link", "tok1");
    expect(guestToken.get("a-link")).toBe("tok1");
    guestToken.clear("a-link");
    expect(guestToken.get("a-link")).toBeNull();
  });
});
