import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GoogleId } from "./google";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const gsi = (): GoogleId => ({ initialize: vi.fn(), renderButton: vi.fn() });

async function fresh() {
  vi.resetModules(); // the loader promise is module state: each test starts from "not loaded"
  return import("./google");
}

describe("loadGoogleIdentity", () => {
  beforeEach(() => {
    delete window.google;
    document.head.querySelectorAll("script").forEach((s) => s.remove());
  });
  afterEach(() => {
    delete window.google;
  });

  it("resolves at once when the script is already on the page", async () => {
    const id = gsi();
    window.google = { accounts: { id } };
    const g = await fresh();
    await expect(g.loadGoogleIdentity()).resolves.toBe(id);
    expect(document.head.querySelector("script")).toBeNull();
  });

  it("adds the GIS script once and resolves when window.google is ready", async () => {
    const g = await fresh();
    const a = g.loadGoogleIdentity();
    const b = g.loadGoogleIdentity(); // concurrent callers share the one load
    const scripts = document.head.querySelectorAll<HTMLScriptElement>(`script[src="${g.GSI_SRC}"]`);
    expect(scripts).toHaveLength(1);
    expect(scripts[0].async).toBe(true);
    const id = gsi();
    window.google = { accounts: { id } }; // what the real script does before firing load
    scripts[0].dispatchEvent(new Event("load"));
    await expect(a).resolves.toBe(id);
    await expect(b).resolves.toBe(id);
    // A later call needs no second script.
    await expect(g.loadGoogleIdentity()).resolves.toBe(id);
    expect(document.head.querySelectorAll("script")).toHaveLength(1);
  });

  it("rejects when the script fails to load, and tries again next time", async () => {
    const g = await fresh();
    const first = g.loadGoogleIdentity();
    document.head.querySelector("script")!.dispatchEvent(new Event("error"));
    await expect(first).rejects.toThrow("gsi_unavailable");
    void g.loadGoogleIdentity().catch(() => {});
    expect(document.head.querySelectorAll("script")).toHaveLength(2);
  });
});

describe("helpers", () => {
  it("fetchGoogleClientId reads auth-config and maps a missing ID to an empty string", async () => {
    const g = await fresh();
    const { api } = await import("@/lib/api");
    vi.mocked(api).mockResolvedValueOnce({ google_client_id: "abc.apps.googleusercontent.com" });
    await expect(g.fetchGoogleClientId()).resolves.toBe("abc.apps.googleusercontent.com");
    expect(api).toHaveBeenCalledWith("/api/users/auth-config/");
    vi.mocked(api).mockResolvedValueOnce({});
    await expect(g.fetchGoogleClientId()).resolves.toBe("");
  });

  it("emailFromCredential decodes the JWT payload and tolerates junk", async () => {
    const g = await fresh();
    const payload = btoa(JSON.stringify({ email: "asha@example.com" })).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(g.emailFromCredential(`h.${payload}.s`)).toBe("asha@example.com");
    expect(g.emailFromCredential("not-a-jwt")).toBe("");
    expect(g.emailFromCredential("")).toBe("");
  });

  it("buttonWidth follows the container but stays inside Google's 200–400px range", async () => {
    const g = await fresh();
    const el = document.createElement("div");
    expect(g.buttonWidth(el)).toBe(400); // jsdom has no layout → the widest allowed
    Object.defineProperty(el, "offsetWidth", { value: 320, configurable: true });
    expect(g.buttonWidth(el)).toBe(320);
    Object.defineProperty(el, "offsetWidth", { value: 900, configurable: true });
    expect(g.buttonWidth(el)).toBe(400);
    Object.defineProperty(el, "offsetWidth", { value: 120, configurable: true });
    expect(g.buttonWidth(el)).toBe(200);
  });
});
