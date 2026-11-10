import { describe, expect, it } from "vitest";

import { authParams, relativeAge, safeRedirect } from "./connect";

describe("authParams", () => {
  it("keeps only the OAuth parameters", () => {
    expect(authParams("?client_id=abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcb&state=s1&evil=1&code_challenge=x")).toEqual({
      client_id: "abc",
      redirect_uri: "https://claude.ai/cb",
      state: "s1",
      code_challenge: "x",
    });
  });
});

describe("safeRedirect", () => {
  it("allows https and loopback http only", () => {
    expect(safeRedirect("https://claude.ai/api/mcp/auth_callback?code=1&state=2")).toBe("https://claude.ai/api/mcp/auth_callback?code=1&state=2");
    expect(safeRedirect("http://localhost:6274/cb?code=1")).toBe("http://localhost:6274/cb?code=1");
    expect(safeRedirect("http://127.0.0.1:9/cb")).toBe("http://127.0.0.1:9/cb");
    expect(safeRedirect("javascript:alert(1)")).toBeNull();
    expect(safeRedirect("http://evil.example/cb")).toBeNull();
    expect(safeRedirect("https://user:pw@evil.example/")).toBeNull();
    expect(safeRedirect("/relative")).toBeNull();
    expect(safeRedirect(undefined)).toBeNull();
  });
});

describe("relativeAge", () => {
  it("formats how long ago a client registered", () => {
    const now = Date.parse("2026-10-17T12:00:00Z");
    expect(relativeAge("2026-10-17T09:00:00Z", "en", now)).toBe("3 hours ago");
    expect(relativeAge("2026-10-15T12:00:00Z", "en", now)).toBe("2 days ago");
    expect(relativeAge("2026-10-17T11:59:30Z", "en", now)).toBe("30 seconds ago");
  });
});
