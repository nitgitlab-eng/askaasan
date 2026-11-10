import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { billing, giftPlan, renewInterval, subNeedsAttention } from "./billing";

vi.mock("./api", async (orig) => ({ ...(await orig<typeof import("./api")>()), api: vi.fn() }));

describe("auto-renew helpers", () => {
  it("labels monthly and yearly periods", () => {
    expect(renewInterval(30)).toBe("month");
    expect(renewInterval(31)).toBe("month");
    expect(renewInterval(365)).toBe("year");
    expect(renewInterval(90)).toBeNull();
  });
  it("flags subscriptions that need the learner", () => {
    expect(subNeedsAttention("halted")).toBe(true);
    expect(subNeedsAttention("pending")).toBe(true);
    expect(subNeedsAttention("active")).toBe(false);
  });
});

describe("family and gift clients", () => {
  afterEach(() => { vi.mocked(api).mockReset(); });

  it("call the family endpoints", async () => {
    vi.mocked(api).mockResolvedValue({});
    await billing.family.invite("appa@home.in");
    await billing.family.accept({ code: "ABC234" });
    await billing.family.remove(7);
    await billing.family.preview("tok/en");
    expect(vi.mocked(api).mock.calls).toEqual([
      ["/api/billing/family/invite/", { method: "POST", json: { email: "appa@home.in" } }],
      ["/api/billing/family/accept/", { method: "POST", json: { code: "ABC234" } }],
      ["/api/billing/family/members/7/remove/", { method: "POST" }],
      ["/api/billing/family/invites/tok%2Fen/"],
    ]);
  });

  it("giftPlan checks out with the gift; a free (100% promo) gift needs no Razorpay", async () => {
    vi.mocked(api).mockResolvedValue({ free: true, plan: "Pro", gift: true });
    const r = await giftPlan("pro", "#f97316", { recipient_email: "paati@home.in", message: "Hi" }, { promo: "GIFTFREE" });
    expect(r).toEqual({ plan: "Pro", free: true, gift: true });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/api/billing/checkout/", {
      method: "POST",
      json: { plan: "pro", promo: "GIFTFREE", gift: { recipient_email: "paati@home.in", message: "Hi" } },
    });
  });
});
