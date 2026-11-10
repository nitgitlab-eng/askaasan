import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme, deviceTheme, resolveTheme } from "./theme";

/** A controllable matchMedia: `dark(true)` flips the device and fires "change" on every open query. */
function fakeMatchMedia(initialDark: boolean) {
  let matches = initialDark;
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  const mql = {
    get matches() {
      return matches;
    },
    media: "(prefers-color-scheme: dark)",
    addEventListener: vi.fn((_: "change", fn: (e: MediaQueryListEvent) => void) => listeners.add(fn)),
    removeEventListener: vi.fn((_: "change", fn: (e: MediaQueryListEvent) => void) => listeners.delete(fn)),
  };
  const dark = (v: boolean) => {
    matches = v;
    for (const fn of listeners) fn({ matches: v } as MediaQueryListEvent);
  };
  return { mql, dark, listeners, matchMedia: vi.fn(() => mql as unknown as MediaQueryList) };
}

describe("theme: follow my device", () => {
  beforeEach(() => delete document.documentElement.dataset.theme);
  afterEach(() => vi.unstubAllGlobals());

  it("resolves system to dark on a dark device and light otherwise", () => {
    vi.stubGlobal("matchMedia", fakeMatchMedia(true).matchMedia);
    expect(deviceTheme()).toBe("dark");
    expect(resolveTheme("system")).toBe("dark");
    expect(resolveTheme("kolam")).toBe("kolam");
    vi.stubGlobal("matchMedia", fakeMatchMedia(false).matchMedia);
    expect(resolveTheme("system")).toBe("light");
  });

  it("paints the device theme and flips live when the device setting changes", () => {
    const fm = fakeMatchMedia(false);
    vi.stubGlobal("matchMedia", fm.matchMedia);
    const stop = applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("light");
    fm.dark(true);
    expect(document.documentElement.dataset.theme).toBe("dark");
    fm.dark(false);
    expect(document.documentElement.dataset.theme).toBe("light");
    stop();
    expect(fm.listeners.size).toBe(0);
    fm.dark(true);
    expect(document.documentElement.dataset.theme).toBe("light"); // no longer following
  });

  it("a fixed theme paints itself and drops any device subscription", () => {
    const fm = fakeMatchMedia(true);
    vi.stubGlobal("matchMedia", fm.matchMedia);
    applyTheme("system");
    expect(fm.listeners.size).toBe(1);
    applyTheme("ocean");
    expect(document.documentElement.dataset.theme).toBe("ocean");
    expect(fm.listeners.size).toBe(0);
    fm.dark(false);
    expect(document.documentElement.dataset.theme).toBe("ocean");
  });

  it("falls back to light without matchMedia", () => {
    vi.stubGlobal("matchMedia", undefined);
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
