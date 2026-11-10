import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { clearOfflineData } from "@/lib/offline";
import { renderPage } from "@/test/render";

import AccountPage from "./Account";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn(async () => null) }));
vi.mock("@/lib/legal", async (orig) => {
  const real = await orig<typeof import("@/lib/legal")>();
  return { ...real, legal: { ...real.legal, deleteAccount: vi.fn(async () => ({ ok: true })) } };
});
vi.mock("@/lib/offline", async (orig) => ({ ...(await orig<typeof import("@/lib/offline")>()), clearOfflineData: vi.fn(async () => {}) }));
vi.mock("@/lib/useMe", async (orig) => ({
  ...(await orig<typeof import("@/lib/useMe")>()),
  useMe: () => ({ data: { has_password: true, consent: {}, preferences: { notifications: {} } } }),
}));

describe("Account deletion (H64)", () => {
  it("clears offline data on this device after the account is deleted", async () => {
    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
    renderPage(<AccountPage />);
    fireEvent.change(screen.getByLabelText(/DELETE/), { target: { value: "DELETE" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: /Delete my account forever/ }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(clearOfflineData).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
});

describe("workshop emails preference", () => {
  it("is on by default and switches off with a PATCH", async () => {
    const { api } = await import("@/lib/api");
    renderPage(<AccountPage />);
    const toggle = screen.getByRole("switch", { name: "Workshop emails" });
    expect(toggle).toHaveAttribute("aria-checked", "true");
    fireEvent.click(toggle);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/users/preferences/", { method: "PATCH", json: { notifications: { email_workshops: false } } }));
  });
});
