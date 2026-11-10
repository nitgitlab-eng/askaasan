import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderPage } from "@/test/render";

import ConnectAuthorize from "./Authorize";

const consent = (mismatch: boolean) => ({
  client: { name: "Claude", redirect_host: "evil.example", redirect_uri: "https://evil.example/cb", registered_at: new Date().toISOString(), new: false, name_mismatch: mismatch },
  scope: "learn",
  orgs: [{ slug: "acme", name: "Acme" }],
});
let mismatch = true;
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => consent(mismatch)) }));

const route = "/connect/authorize?client_id=c&redirect_uri=https%3A%2F%2Fevil.example%2Fcb&response_type=code&state=s&code_challenge=x&code_challenge_method=S256";

describe("Connect Claude consent (H27)", () => {
  it("warns when the app's name doesn't match where it sends you", async () => {
    mismatch = true;
    renderPage(<ConnectAuthorize />, { route, path: "/connect/authorize" });
    expect(await screen.findByText(/calls itself “Claude” but sends you to evil\.example, which is not Claude/)).toBeInTheDocument();
  });

  it("shows no such warning otherwise", async () => {
    mismatch = false;
    renderPage(<ConnectAuthorize />, { route, path: "/connect/authorize" });
    expect(await screen.findByText(/Acme/)).toBeInTheDocument();
    expect(screen.queryByText(/which is not Claude/)).toBeNull();
  });
});
