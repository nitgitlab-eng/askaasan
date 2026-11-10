import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DialogHost } from "@/components/dialog";
import { TemplateEditor } from "@/components/certificates/TemplateEditor";
import { canSee } from "@/lib/admin";
import { api } from "@/lib/api";
import { useAuth } from "@/stores/auth";
import { apiRoutes, renderPage } from "@/test/render";

import { AdminLayout } from "./AdminLayout";
import AdminRefunds from "./Refunds";
import AdminUsers from "./Users";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
vi.mock("@/components/tour/tourStore", () => ({ startTour: vi.fn(), useAutoTour: vi.fn() }));
vi.mock("@/components/tour/Tour", () => ({ TourHost: () => null }));

const me = (roles: string[]) => ({
  id: 1, email: "staff@aasan.in", email_verified: true, is_staff: true, staff_roles: roles, is_creator: false, can_author: true, has_password: true,
  profile: { display_name: "", language: "en" }, preferences: { appearance: {}, mascot: {}, learning: {} }, consent: { required: false },
});

function renderLayout(roles: string[]) {
  vi.mocked(api).mockImplementation(apiRoutes({ "/api/users/me/": me(roles) }) as never);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/admin/overview"]}>
        <Routes><Route path="/admin" element={<AdminLayout />}><Route path="overview" element={<p>overview</p>} /></Route></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("admin console", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    useAuth.setState({ access: "token", signedIn: true });
  });
  afterEach(() => {
    useAuth.setState({ access: null, signedIn: false });
  });

  it("shows each role only its sections", async () => {
    renderLayout(["finance"]);
    expect(await screen.findByRole("link", { name: "Refunds" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Staff & audit log" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Certificates" })).toBeNull();
    expect(canSee(["content"], "certificates")).toBe(true);
    expect(canSee(["content"], "refunds")).toBe(false);
    expect(canSee(["superadmin"], "staff")).toBe(true);
    expect(canSee([], "overview")).toBe(false);
  });

  it("users: list, open one and deactivate after confirming", async () => {
    const acted = vi.fn();
    const row = { id: 9, email: "arun@school.in", name: "Arun", joined: "2026-10-01", last_login: null, active: true, verified: true, staff: false, creator: false, minor: false, orgs: 1, courses: 2 };
    const detail = { ...row, roles: [], age_band: "adult", guardian_email: "", plans: [], payments: { count: 0, total_paise: 0 }, orgs: [], courses: { own: 2, enrolled: 0 }, certificates: [], ai_30d: { calls: 3, tokens: 1200 }, devices: { passkeys: 0, extension: 0 } };
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/users/9/action/": (init) => { acted(init?.json); return { ...detail, active: false }; },
      "/api/admin/users/9/": detail,
      "/api/admin/users/": { results: [row], count: 1, page: 1, pages: 1, totals: { total: 5, active_7d: 2 } },
    }) as never);
    renderPage(<AdminUsers />);
    fireEvent.click(await screen.findByText("arun@school.in"));
    fireEvent.click(await screen.findByRole("button", { name: "Deactivate" }));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(acted).toHaveBeenCalledWith({ action: "deactivate" }));
    expect(await screen.findByRole("button", { name: "Reactivate" })).toBeInTheDocument();
  });

  it("refunds: find a paid order and refund part of it", async () => {
    const sent = vi.fn();
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/payments/orders/": { orders: [{ id: 4, email: "buyer@x.in", plan: "Pro", amount_paise: 19900, refunded_paise: 0, status: "paid", mode: "live", paid_at: "2026-10-10", payment_id: "pay_1" }] },
      "/api/admin/refunds/": (init) => (init?.method === "POST" ? sent(init.json) : { results: [], count: 0, page: 1, pages: 1, total_paise: 0 }),
    }) as never);
    renderPage(<AdminRefunds />);
    fireEvent.change(screen.getByLabelText("Find order"), { target: { value: "buyer" } });
    fireEvent.click(screen.getByRole("button", { name: /Find paid orders/ }));
    fireEvent.click(await screen.findByText(/buyer@x.in/));
    fireEvent.change(screen.getByLabelText(/Amount/), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Charged twice" } });
    fireEvent.click(screen.getByRole("button", { name: "Refund" }));
    fireEvent.click(await screen.findByRole("button", { name: "OK" }));
    await waitFor(() => expect(sent).toHaveBeenCalledWith({ order_id: 4, amount_paise: 5000, reason: "Charged twice", end_access: false }));
  });

  it("template editor saves the chosen scope and look", async () => {
    const saved = vi.fn();
    vi.mocked(api).mockImplementation(apiRoutes({
      "/api/admin/certificate-templates/": (init) => (init?.method === "POST" ? (saved(init.json), { id: 3, ...(init.json as object) }) : []),
    }) as never);
    render(
      <QueryClientProvider client={new QueryClient()}>
        <DialogHost />
        <TemplateEditor base="/api/admin/certificate-templates/" />
      </QueryClientProvider>,
    );
    fireEvent.change(screen.getByLabelText("For"), { target: { value: "workshop" } });
    fireEvent.change(screen.getByLabelText("Layout"), { target: { value: "modern" } });
    fireEvent.change(screen.getByLabelText("Signatory"), { target: { value: "Dr. Meena" } });
    fireEvent.click(screen.getByRole("button", { name: /Save/ }));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(saved.mock.calls[0][0]).toMatchObject({ kind: "workshop", language: "", layout: "modern", signatory_name: "Dr. Meena", active: true });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });
});
