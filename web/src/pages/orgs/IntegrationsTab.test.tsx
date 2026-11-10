import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { apiRoutes, renderPage } from "@/test/render";

import IntegrationsTab from "./IntegrationsTab";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const HOOK = {
  id: 7, url: "https://hr.example.com/hook", events: ["course.completed"], active: true, failures: 0, disabled_reason: "",
  created_at: "2026-10-01T00:00:00Z", last_delivery: null,
};

describe("IntegrationsTab", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("shows a new API key exactly once and never in the list", async () => {
    let keys: object[] = [];
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/orgs/acme/integrations/keys/": (init) => {
        if (init?.method === "POST") {
          keys = [{ id: 1, name: "HR", prefix: "ak_AbCdEfGh", scopes: ["read:progress"], created_at: "", created_by: "o@x.in", last_used_at: null, revoked_at: null }];
          return { ...keys[0], key: "ak_AbCdEfGhSECRETSECRETSECRETSECRETSECRET12" };
        }
        return { keys, scopes: [] };
      },
      "/api/orgs/acme/integrations/webhooks/": { webhooks: [], events: [] },
    }) as never);
    renderPage(<IntegrationsTab slug="acme" />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Key name" }), { target: { value: "HR" } });
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));
    expect(await screen.findByTestId("shown-once")).toHaveTextContent("ak_AbCdEfGhSECRET");
    expect(api).toHaveBeenCalledWith("/api/orgs/acme/integrations/keys/", { method: "POST", json: { name: "HR", scopes: ["read:progress"] } });
    expect(await screen.findByText("ak_AbCdEfGh…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "I've saved it" }));
    await waitFor(() => expect(screen.queryByTestId("shown-once")).toBeNull());
    expect(screen.queryByText(/SECRETSECRET/)).toBeNull();
  });

  it("explains why a webhook address is refused", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/orgs/acme/integrations/keys/": { keys: [], scopes: [] },
      "/api/orgs/acme/integrations/webhooks/": (init) => {
        if (init?.method === "POST") throw new ApiError(400, { code: "bad_url", reason: "private_address" });
        return { webhooks: [], events: [] };
      },
    }) as never);
    renderPage(<IntegrationsTab slug="acme" />);
    fireEvent.change(await screen.findByRole("textbox", { name: "Webhook address (https)" }), { target: { value: "https://internal.corp/x" } });
    fireEvent.click(screen.getByRole("button", { name: "Add webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("it points to a private or local address");
  });

  it("sends a test message and opens the delivery log", async () => {
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/orgs/acme/integrations/keys/": { keys: [], scopes: [] },
      "/api/orgs/acme/integrations/webhooks/7/test/": { id: 3, event: "ping", status: "ok", attempt: 1, response_status: 200, last_error: "", next_try_at: null, created_at: "", delivered_at: "" },
      "/api/orgs/acme/integrations/webhooks/7/deliveries/": { results: [{ id: 2, event: "course.completed", status: "dead", attempt: 5, response_status: 500, last_error: "http_500", next_try_at: null, created_at: "2026-10-01T00:00:00Z", delivered_at: null }], count: 1, page: 1, pages: 1 },
      "/api/orgs/acme/integrations/webhooks/": { webhooks: [HOOK], events: [] },
    }) as never);
    renderPage(<IntegrationsTab slug="acme" />);
    fireEvent.click(await screen.findByRole("button", { name: /Send test/ }));
    expect(await screen.findByText("Test message delivered.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Delivery log" }));
    expect(await screen.findByText(/try 5 · HTTP 500 · http_500/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send again" })).toBeInTheDocument();
  });
});
