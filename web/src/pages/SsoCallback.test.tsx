import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { resendVerification, useCompleteLogin } from "@/lib/auth";
import { renderPage } from "@/test/render";

import SsoCallback from "./SsoCallback";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/lib/auth", async (orig) => ({
  ...(await orig<typeof import("@/lib/auth")>()),
  useCompleteLogin: vi.fn(),
  resendVerification: vi.fn(async () => "Verification email sent."),
}));

const complete = vi.fn();
let n = 0;
const visit = (query: string) => {
  window.history.replaceState(null, "", `/sso/callback?${query}`);
  return renderPage(<SsoCallback />);
};

describe("SsoCallback", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    complete.mockReset();
    vi.mocked(useCompleteLogin).mockReturnValue(complete);
    n += 1;
  });

  it("finishes the sign-in once and sends new accounts to onboarding", async () => {
    const payload = { access: "a", user: { id: 1 }, created: true };
    vi.mocked(api).mockResolvedValue(payload as never);
    visit(`code=c1&state=s${n}`);
    await waitFor(() => expect(complete).toHaveBeenCalledWith(payload, { to: "/onboarding" }));
    expect(api).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api).mock.calls[0][0]).toBe("/api/users/sso/callback/");
    expect((vi.mocked(api).mock.calls[0][1] as { json: { code: string; state: string } }).json).toMatchObject({ code: "c1", state: `s${n}` });
  });

  it("an unverified existing account is asked to verify, with a resend button", async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(409, { detail: "account_unverified", email: "k@acme.in" }));
    visit(`code=c&state=s${n}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(/isn't verified yet/);
    fireEvent.click(screen.getByRole("button", { name: "Resend the verification email" }));
    await waitFor(() => expect(resendVerification).toHaveBeenCalledWith("k@acme.in"));
    expect(complete).not.toHaveBeenCalled();
  });

  it("maps refusals to plain messages", async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(403, { detail: "sso_domain_not_allowed" }));
    visit(`code=c&state=s${n}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(/doesn't allow this account/);
    expect(screen.getByRole("link", { name: "Back to sign in" })).toHaveAttribute("href", "/login");
  });

  it("an expired or replayed state, a cancelled sign-in, or a missing code", async () => {
    vi.mocked(api).mockRejectedValue(new ApiError(400, { detail: "invalid_state" }));
    const { unmount } = visit(`code=c&state=s${n}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(/expired or was already used/);
    unmount();
    const r2 = visit("error=access_denied&state=x");
    expect(await screen.findByRole("alert")).toHaveTextContent(/cancelled/);
    r2.unmount();
    visit("");
    expect(await screen.findByRole("alert")).toHaveTextContent(/expired/);
    expect(api).toHaveBeenCalledTimes(1);
  });
});
