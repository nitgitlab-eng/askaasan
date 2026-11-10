import { describe, expect, it } from "vitest";

import { addDays, isoDay } from "./study";

describe("date helpers (local days, not UTC)", () => {
  it("formats and adds days across month and year ends", () => {
    expect(isoDay(new Date(2026, 0, 5))).toBe("2026-01-05");
    expect(addDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addDays("2026-12-29", 7)).toBe("2027-01-05");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });
});
