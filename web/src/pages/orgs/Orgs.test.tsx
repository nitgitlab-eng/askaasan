import { fireEvent, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { renderPage } from "@/test/render";

import OrgsPage, { JoinOrInvite } from "./Orgs";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

describe("Accept invite (R20)", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    window.history.pushState({}, "", "/invite/tok123");
  });

  it("POSTs the one-time token exactly once, even under StrictMode", async () => {
    vi.mocked(api).mockResolvedValue({ name: "Acme School", slug: "acme", role: "learner" } as never);
    renderPage(<StrictMode><JoinOrInvite mode="invite" /></StrictMode>);
    expect(await screen.findByText(/Acme School/)).toBeInTheDocument();
    expect(vi.mocked(api).mock.calls.filter((c) => c[0] === "/api/orgs/invites/tok123/accept/")).toHaveLength(1);
  });

  it("asks an unverified learner to verify first and can resend the email", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path.includes("/accept/")) throw new ApiError(403, { code: "verify_email_first" });
      return {};
    }) as never);
    renderPage(<JoinOrInvite mode="invite" />);
    expect(await screen.findByText(/Verify your email first/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/email-verification/request/", { method: "POST" }));
    expect(await screen.findByText(/Verification email sent/)).toBeInTheDocument();
  });

  it.each([
    [410, "invite_revoked", /no longer valid/],
    [409, "staff_use_admin", /added by an admin/],
  ])("shows a translated message for %s %s", async (status, code, text) => {
    vi.mocked(api).mockRejectedValue(new ApiError(status, { code }) as never);
    renderPage(<JoinOrInvite mode="invite" />);
    expect(await screen.findByText(text)).toBeInTheDocument();
  });
});

describe("Create organization", () => {
  it("shows an error when creating fails instead of doing nothing", async () => {
    vi.mocked(api).mockImplementation((async (path: string, init?: { method?: string }) => {
      if (path === "/api/orgs/" && init?.method === "POST") throw new ApiError(429, { code: "too_many_orgs" });
      return [];
    }) as never);
    renderPage(<OrgsPage />);
    fireEvent.change(screen.getByRole("textbox", { name: "Organization name" }), { target: { value: "My School" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });
});
