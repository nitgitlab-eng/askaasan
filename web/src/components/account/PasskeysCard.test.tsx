import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { renderPage } from "@/test/render";

import { PasskeysCard } from "./PasskeysCard";

vi.mock("@simplewebauthn/browser", () => ({
  browserSupportsWebAuthn: () => true,
  startRegistration: vi.fn(async () => ({ id: "cred" })),
  startAuthentication: vi.fn(async () => ({ id: "auth" })),
}));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));

const calls = () => vi.mocked(api).mock.calls.map((c) => [c[0], (c[1] as { json?: unknown } | undefined)?.json]);

describe("Adding a passkey needs a recent sign-in (H7)", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "old", signedIn: true });
  });

  it("re-authenticates with the password, then retries and registers", async () => {
    let begins = 0;
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path === "/api/users/passkeys/") return [];
      if (path === "/api/users/passkey/register/begin/") {
        if (begins++ === 0) throw new ApiError(403, { code: "reauth_required", methods: ["password"] });
        return { key: "k", options: "{}" };
      }
      if (path === "/api/users/reauth/") return { access: "fresh" };
      return null;
    }) as never);
    renderPage(<PasskeysCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    const dialog = await screen.findByRole("dialog", { name: /enter your password again/ });
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "s3cret" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm it's you" }));
    const naming = await screen.findByRole("dialog", { name: /name/i });
    fireEvent.click(within(naming).getByRole("button", { name: "OK" }));
    await waitFor(() => expect(calls()).toContainEqual(["/api/users/passkey/register/complete/", expect.objectContaining({ key: "k" })]));
    expect(calls()).toContainEqual(["/api/users/reauth/", { password: "s3cret" }]);
    expect(useAuth.getState().access).toBe("fresh");
    expect(begins).toBe(2);
  });

  it("an unverified email is told to verify first, with a resend button", async () => {
    vi.mocked(api).mockImplementation((async (path: string) => {
      if (path === "/api/users/passkeys/") return [];
      if (path === "/api/users/passkey/register/begin/") throw new ApiError(403, { code: "email_unverified" });
      return null;
    }) as never);
    renderPage(<PasskeysCard />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a passkey" }));
    expect(await screen.findByText(/Verify your email first/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/email-verification/request/", { method: "POST" }));
  });
});
