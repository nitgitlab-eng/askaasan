import { describe, expect, it } from "vitest";

import { isProvider, parseCallback, replanSummary } from "./calendar";

describe("calendar connect helpers", () => {
  it("reads the OAuth callback query", () => {
    expect(parseCallback("?code=abc&state=xyz&scope=x")).toEqual({ kind: "ok", code: "abc", state: "xyz" });
    expect(parseCallback("?error=access_denied&state=xyz")).toEqual({ kind: "denied" });
    expect(parseCallback("?code=abc")).toEqual({ kind: "invalid" });
    expect(parseCallback(`?code=${"a".repeat(3000)}&state=s`)).toEqual({ kind: "invalid" });
  });
  it("only knows the two providers", () => {
    expect(isProvider("google")).toBe(true);
    expect(isProvider("microsoft")).toBe(true);
    expect(isProvider("yahoo")).toBe(false);
    expect(isProvider(undefined)).toBe(false);
  });
  it("summarises a re-plan", () => {
    expect(replanSummary({ moved: 2, unplaced: 0, needs_reconnect: [] })).toBe("moved");
    expect(replanSummary({ moved: 0, unplaced: 0, needs_reconnect: [] })).toBe("nochange");
    expect(replanSummary({ moved: 3, unplaced: 1, needs_reconnect: [] })).toBe("unplaced");
    expect(replanSummary({ moved: 3, unplaced: 1, needs_reconnect: ["google"] })).toBe("reconnect");
  });
});
