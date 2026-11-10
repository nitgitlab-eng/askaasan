import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { renderPage } from "@/test/render";

import { PendingInvites } from "./PendingInvites";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string, init?: { method?: string }) =>
    init?.method === "DELETE" ? null : path === "/api/orgs/acme/invitations/" ? [{ id: 3, email: "new@school.in", role: "learner", created_at: "" }] : null) as never);
});

describe("Pending invitations: revoke", () => {
  it("asks first, and Cancel keeps the invitation", async () => {
    renderPage(<PendingInvites slug="acme" />);
    fireEvent.click(await screen.findByRole("button", { name: /Revoke/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api).mock.calls.some((c) => (c[1] as { method?: string } | undefined)?.method === "DELETE")).toBe(false);
  });

  it("confirming sends DELETE for that invitation", async () => {
    renderPage(<PendingInvites slug="acme" />);
    fireEvent.click(await screen.findByRole("button", { name: /Revoke/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/orgs/acme/invitations/3/", { method: "DELETE" }));
  });
});

describe("Revoking clears the unsent-link notice (walkthrough bug)", () => {
  it("drops the revoked address's link, and the whole notice when none remain", async () => {
    const { dropInviteLink } = await import("@/lib/orgs");
    const mail = { emailed: false, links: [{ email: "a@x.in", link: "L1" }, { email: "b@x.in", link: "L2" }] };
    expect(dropInviteLink(mail, "A@x.in")?.links).toEqual([{ email: "b@x.in", link: "L2" }]);
    expect(dropInviteLink({ emailed: false, links: [{ email: "a@x.in", link: "L1" }] }, "a@x.in")).toBeNull();
  });

  it("tells the page which address was revoked", async () => {
    const onRevoked = vi.fn();
    renderPage(<PendingInvites slug="acme" onRevoked={onRevoked} />);
    fireEvent.click(await screen.findByRole("button", { name: /Revoke/ }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(onRevoked).toHaveBeenCalledWith("new@school.in"));
  });
});
