import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/stores/auth";

import { clearOfflineData, flushQueue, offlineQueue } from "./offline";

describe("offline answer queue", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuth.setState({ access: "tok", signedIn: true });
    vi.stubGlobal("navigator", { ...navigator, onLine: true });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps only the latest answer per activity", () => {
    offlineQueue.add({ key: "attempt:1", url: "/a/1", json: { answer: 1 } });
    offlineQueue.add({ key: "attempt:1", url: "/a/1", json: { answer: 2 } });
    offlineQueue.add({ key: "complete:9", url: "/c/9", json: {} });
    expect(offlineQueue.list().map((q) => q.json)).toEqual([{ answer: 2 }, {}]);
  });

  it("sends queued answers, keeps network failures, drops permanent rejections", async () => {
    offlineQueue.add({ key: "attempt:1", url: "/ok", json: {} });
    offlineQueue.add({ key: "attempt:2", url: "/down", json: {} });
    offlineQueue.add({ key: "attempt:3", url: "/gone", json: {} });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/down") throw new TypeError("Failed to fetch");
      return new Response("{}", { status: url === "/gone" ? 404 : 200 });
    }));
    expect(await flushQueue()).toBe(1);
    expect(offlineQueue.list().map((q) => q.key)).toEqual(["attempt:2"]);
  });

  it("does nothing while offline", async () => {
    vi.stubGlobal("navigator", { ...navigator, onLine: false });
    offlineQueue.add({ key: "attempt:1", url: "/ok", json: {} });
    expect(await flushQueue()).toBe(0);
    expect(offlineQueue.list()).toHaveLength(1);
  });
});

describe("clearOfflineData (H63)", () => {
  it("also forgets guest visitor tokens", async () => {
    localStorage.setItem("aasan-guest-tokens", JSON.stringify({ demo: "gtok" }));
    await clearOfflineData();
    expect(localStorage.getItem("aasan-guest-tokens")).toBeNull();
  });
});

