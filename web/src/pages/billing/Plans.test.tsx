import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { LIMIT_KEYS } from "@/lib/billing";
import { renderPage } from "@/test/render";

import PlansPage from "./Plans";

const limits = { ai_courses_per_month: 2, mentor_messages_per_day: 20, documents: 3, voice_minutes_per_day: 10, live_minutes_per_day: 10, lab_ai_per_day: 5, tts_chars_per_day: 5000 };
const free = { code: "free", name: "Free", price_paise: 0, period_days: 0, limits };
const pro = { code: "pro", name: "Pro", price_paise: 19900, period_days: 30, limits: { ...limits, tts_chars_per_day: null } };
const fam = { code: "family", name: "Family Plus", price_paise: 29900, period_days: 30, limits, family: true, max_members: 4 };
const usage = Object.fromEntries(Object.entries(limits).map(([k, max]) => [k, { used: k === "tts_chars_per_day" ? 1200 : 0, max }]));
const checkout = { available: false, mode: null as string | null };

vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  api: vi.fn(async (path: string) => {
    if (path === "/api/billing/") return { plan: { ...free, source: null }, paid_until: null, usage, plans: [free, pro, fam], checkout };
    if (path === "/api/billing/history/") return [];
    if (path === "/api/billing/subscription/") return { subscription: null, access_until: null };
    if (path === "/api/billing/checkout/") return { free: true, plan: "Pro", gift: true };
    return null;
  }),
}));

describe("Plans page: read-aloud limit (HDE)", () => {
  it("is a known limit", () => {
    expect(LIMIT_KEYS).toContain("tts_chars_per_day");
  });

  it("shows today's read-aloud meter and each plan's read-aloud allowance", async () => {
    renderPage(<PlansPage />);
    expect(await screen.findByText("Read-aloud characters today")).toBeInTheDocument();
    expect(screen.getByText("1200 / 5000")).toBeInTheDocument();
    expect(screen.getAllByText(/5000 read-aloud characters a day/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Unlimited read-aloud/)).toBeInTheDocument();
  });
});

describe("Plans page: family and gifts", () => {
  it("marks family plans with how many people share them", async () => {
    renderPage(<PlansPage />);
    expect(await screen.findByText("Share with up to 4 people (you included)")).toBeInTheDocument();
  });

  it("fills in a gift code from the email link", async () => {
    renderPage(<PlansPage />, { route: "/plans?code=abcd-efgh-jkmn" });
    expect(await screen.findByDisplayValue("ABCD-EFGH-JKMN")).toBeInTheDocument();
  });

  it("gifts a plan through the dialog", async () => {
    checkout.available = true;
    renderPage(<PlansPage />);
    fireEvent.click((await screen.findAllByRole("button", { name: "Gift this plan" }))[0]);
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Gift Pro");
    fireEvent.change(screen.getByLabelText("Their email address"), { target: { value: "paati@home.in" } });
    fireEvent.change(screen.getByLabelText(/short message/), { target: { value: "Happy birthday" } });
    fireEvent.click(screen.getByRole("button", { name: "Pay ₹199" }));
    expect(await screen.findByText("Gift paid! We've emailed the Pro code to paati@home.in.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/checkout/", { method: "POST", json: { plan: "pro", gift: { recipient_email: "paati@home.in", message: "Happy birthday" } } });
    checkout.available = false;
  });
});
