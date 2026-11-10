import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "@/lib/api";
import { resendVerification, useCompleteLogin } from "@/lib/auth";
import type { GoogleId } from "@/lib/google";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import { apiRoutes, renderPage } from "@/test/render";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/lib/auth", async (orig) => ({
  ...(await orig<typeof import("@/lib/auth")>()),
  useCompleteLogin: vi.fn(),
  resendVerification: vi.fn(async () => "Verification email sent. Check your inbox."),
}));

const CLIENT_ID = "123-abc.apps.googleusercontent.com";
const credentialFor = (email: string) => `h.${btoa(JSON.stringify({ email })).replace(/=+$/, "")}.s`;

let gsi: GoogleId & { callback?: (r: { credential: string }) => void };
let complete: ReturnType<typeof useCompleteLogin> & ReturnType<typeof vi.fn>;

function mockApi(clientId: string, google: () => unknown = () => ({})) {
  vi.mocked(api).mockImplementation(apiRoutes({ "/api/users/auth-config/": { google_client_id: clientId }, "/api/users/google/": google }) as typeof api);
}

/** Lets Google "click" the button: GIS calls the callback registered in initialize(). */
async function receiveCredential(credential: string) {
  await waitFor(() => expect(gsi.callback).toBeTypeOf("function"));
  await act(async () => {
    await gsi.callback!({ credential });
  });
}

beforeEach(() => {
  complete = vi.fn() as typeof complete;
  vi.mocked(useCompleteLogin).mockReturnValue(complete);
  gsi = {
    initialize: vi.fn((cfg) => {
      gsi.callback = cfg.callback;
    }),
    renderButton: vi.fn((el: HTMLElement) => {
      el.innerHTML = '<div role="button" data-gsi>Continue with Google</div>';
    }),
  };
  window.google = { accounts: { id: gsi } };
});

afterEach(() => {
  delete window.google;
  vi.mocked(api).mockReset();
});

describe.each([
  ["Login", () => <Login />, "/login"],
  ["Signup", () => <Signup />, "/signup"],
])("Google sign-in on %s", (_name, page, route) => {
  it("renders nothing when the server has no client ID", async () => {
    mockApi("");
    renderPage(page(), { route });
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/auth-config/"));
    await act(async () => {}); // let the config answer settle
    expect(screen.queryByTestId("google-signin")).toBeNull();
    expect(gsi.initialize).not.toHaveBeenCalled();
    expect(document.querySelector("[data-gsi]")).toBeNull();
  });

  it("initialises GIS and renders the official button when an ID is set", async () => {
    mockApi(CLIENT_ID);
    renderPage(page(), { route });
    await waitFor(() => expect(gsi.initialize).toHaveBeenCalledWith(expect.objectContaining({ client_id: CLIENT_ID, callback: expect.any(Function) })));
    expect(gsi.renderButton).toHaveBeenCalledWith(expect.any(HTMLElement), expect.objectContaining({ theme: "outline", size: "large", width: 400 }));
    expect(await screen.findByRole("button", { name: "Continue with Google" })).toHaveAttribute("data-gsi");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("posts the credential and completes login like password sign-in", async () => {
    const payload = { access: "tok", user: { id: 1 }, created: false };
    mockApi(CLIENT_ID, () => payload);
    renderPage(page(), { route });
    await receiveCredential("cred-1");
    expect(api).toHaveBeenCalledWith("/api/users/google/", { method: "POST", json: { credential: "cred-1", language: "en" } });
    expect(complete).toHaveBeenCalledWith(payload, undefined);
  });

  it("sends a brand-new account to onboarding", async () => {
    const payload = { access: "tok", user: { id: 2 }, created: true };
    mockApi(CLIENT_ID, () => payload);
    renderPage(page(), { route });
    await receiveCredential("cred-2");
    expect(complete).toHaveBeenCalledWith(payload, { to: "/onboarding" });
  });

  it.each([
    [401, { detail: "invalid_google_token" }, "Google sign-in didn't go through. Try again."],
    [401, { detail: "google_email_unverified" }, "Your Google email isn't verified."],
    [429, { detail: "throttled" }, "Too many attempts. Please wait 15 minutes, or reset your password."],
    [500, null, "Something went wrong"],
  ])("shows the message for a %s %j answer", async (status, data, text) => {
    mockApi(CLIENT_ID, () => {
      throw new ApiError(status, data);
    });
    renderPage(page(), { route });
    await receiveCredential("cred-x");
    expect(screen.getByRole("alert")).toHaveTextContent(text);
    expect(complete).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Resend" })).toBeNull();
  });

  it("409: explains the unverified account and can resend the link to that address", async () => {
    mockApi(CLIENT_ID, () => {
      throw new ApiError(409, { detail: "account_unverified" });
    });
    renderPage(page(), { route });
    await receiveCredential(credentialFor("asha@example.com"));
    expect(screen.getByRole("alert")).toHaveTextContent("An account with this email already exists but isn't verified yet. Check your inbox for the verification link.");
    fireEvent.click(screen.getByRole("button", { name: "Resend" }));
    await waitFor(() => expect(resendVerification).toHaveBeenCalledWith("asha@example.com"));
    expect(await screen.findByRole("status")).toHaveTextContent("Verification email sent");
    expect(complete).not.toHaveBeenCalled();
  });
});
