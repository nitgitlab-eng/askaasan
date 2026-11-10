import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import { SsoCard } from "./SsoCard";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const CFG = {
  provider: "google", client_id: "cid", client_secret: "••••9876", tenant_id: "", hosted_domains: ["acme.in"], default_role: "learner",
  default_group_id: null, enabled: true, enforced: false, redirect_uri: "https://app.aasan.in/sso/callback",
  domains: [
    { id: 1, domain: "acme.in", verified: true, verified_at: "", last_checked_at: null, failing_since: null, txt_name: "acme.in", txt_alt_name: "_aasan.acme.in", txt_value: "aasan-verify=t1" },
    { id: 2, domain: "acme.co", verified: false, verified_at: null, last_checked_at: null, failing_since: null, txt_name: "acme.co", txt_alt_name: "_aasan.acme.co", txt_value: "aasan-verify=t2" },
  ],
};

function routes(role: string, extra: Record<string, unknown> = {}) {
  return apiRoutes({
    "/api/orgs/acme/sso/domains/2/verify/": () => { throw new ApiError(400, { code: "txt_not_found" }); },
    "/api/orgs/acme/sso/": (init?: { method?: string; json?: unknown }) => (init?.method === "PUT" ? { ...CFG, ...(init.json as object) } : CFG),
    "/api/orgs/acme/groups/": [{ id: 5, name: "Sales", join_code: "X", members: 3 }],
    "/api/orgs/acme/": { id: 1, slug: "acme", name: "Acme", kind: "company", role, members: 1, groups: 1 },
    ...extra,
  });
}

describe("SsoCard", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("shows TXT instructions, the redirect URI and never the secret itself", async () => {
    vi.mocked(api).mockImplementation(routes("owner") as never);
    renderPage(<SsoCard slug="acme" />);
    expect(await screen.findByText("aasan-verify=t2")).toBeInTheDocument();
    expect(screen.getByText(/_aasan\.acme\.co/)).toBeInTheDocument();
    expect(screen.getByText("https://app.aasan.in/sso/callback")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Saved \(••••9876\)/)).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't find the TXT record/);
  });

  it("saves only what changed, including a new secret", async () => {
    vi.mocked(api).mockImplementation(routes("admin") as never);
    renderPage(<SsoCard slug="acme" />);
    fireEvent.change(await screen.findByLabelText("Client secret"), { target: { value: "new-secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Save SSO settings" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/orgs/acme/sso/", { method: "PUT", json: { client_secret: "new-secret" } }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.getByText("Only an owner can require SSO.")).toBeInTheDocument();
  });

  it("requiring SSO asks the owner to confirm first", async () => {
    vi.mocked(api).mockImplementation(routes("owner") as never);
    renderPage(<SsoCard slug="acme" />);
    fireEvent.click(await screen.findByRole("switch", { name: /Require SSO/ }));
    fireEvent.click(await screen.findByRole("button", { name: /OK|Confirm|Yes/ }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/orgs/acme/sso/", { method: "PUT", json: { enforced: true } }));
  });
});
