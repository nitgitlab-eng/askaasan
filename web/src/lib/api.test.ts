import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/stores/auth";

import { api, bootAuth, refreshTokens } from "./api";

const reauth = vi.hoisted(() => vi.fn());
vi.mock("./auth", () => ({ reauthenticate: reauth }));

describe("refreshTokens", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shares one in-flight request between concurrent callers (single-use refresh tokens)", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls++;
      await new Promise((r) => setTimeout(r, 10));
      return new Response(JSON.stringify({ access: `a${calls}` }), { status: 200 });
    }));
    useAuth.setState({ access: null, signedIn: true });
    const [a, b] = await Promise.all([refreshTokens(), refreshTokens(), bootAuth()]);
    expect(a && b).toBe(true);
    expect(calls).toBe(1);
    expect(useAuth.getState().access).toBe("a1");
    // A later refresh is a fresh request.
    await refreshTokens();
    expect(calls).toBe(2);
  });

  it("keeps the learner signed in when the server is unreachable, ends it only on a real rejection", async () => {
    let status = 502;
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
    useAuth.setState({ access: null, signedIn: true, ready: false });
    await bootAuth([1, 1]);
    expect(useAuth.getState()).toMatchObject({ signedIn: true, access: null, ready: true });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3); // first try + 2 retries

    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network down"); }));
    expect(await refreshTokens()).toBe(false);
    expect(useAuth.getState().signedIn).toBe(true);

    status = 401;
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
    expect(await refreshTokens()).toBe(false);
    expect(useAuth.getState().signedIn).toBe(false);
  });
});

describe("admin changes that need a recent sign-in", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    reauth.mockReset();
  });

  const reauthRequired = () => new Response(JSON.stringify({ code: "reauth_required", methods: ["password"] }), { status: 403 });

  it("asks the admin to prove it's them once, then sends the change again", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(reauthRequired()).mockResolvedValueOnce(new Response(JSON.stringify({ ok: 1 }), { status: 200 })));
    reauth.mockResolvedValue(true);
    useAuth.setState({ access: "old", signedIn: true });
    expect(await api("/api/admin/site/", { method: "PATCH", json: { legal_name: "x" } })).toEqual({ ok: 1 });
    expect(reauth).toHaveBeenCalledWith(["password"]);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  });

  it("gives up with the error when the admin cancels, and never prompts outside the admin console", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => reauthRequired()));
    reauth.mockResolvedValue(false);
    await expect(api("/api/admin/site/", { method: "PATCH", json: {} })).rejects.toMatchObject({ status: 403 });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    reauth.mockClear();
    await expect(api("/api/users/passkey/register/begin/", { method: "POST" })).rejects.toMatchObject({ status: 403 });
    expect(reauth).not.toHaveBeenCalled(); // that screen runs its own re-auth
  });
});
