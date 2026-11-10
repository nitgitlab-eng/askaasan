import { expect, test } from "../fixtures";

/** Stand-in for Razorpay Checkout: records what the app opens it with. No request ever reaches Razorpay. */
const FAKE_CHECKOUT = `
window.Razorpay = function (opts) {
  this.opts = opts;
  this.on = function () {};
  this.open = function () { window.__rzp = { opened: true, opts: opts }; };
};`;

test.describe("billing", () => {
  test("plans are listed; Upgrade opens checkout (stubbed) and nothing is charged", async ({ page, api }) => {
    let checkoutBody: Record<string, unknown> | null = null;
    // The order is stubbed too, so the API never talks to Razorpay from a test.
    await page.route("**/api/billing/checkout/", async (route) => {
      checkoutBody = route.request().postDataJSON();
      await route.fulfill({ json: { order_id: "order_e2e_test", amount: 14900, currency: "INR", key_id: "rzp_test_e2e", name: "Aasan", description: "Aasan Plus · Monthly", mode: "test", prefill: { email: "x@example.com", name: "E2E" } } });
    });
    await page.route("https://checkout.razorpay.com/**", (route) => route.fulfill({ contentType: "application/javascript", body: FAKE_CHECKOUT }));

    await page.goto("/plans");
    await expect(page.getByRole("heading", { name: "Plans & billing" })).toBeVisible();
    await expect(page.getByText("₹149 / 30 days")).toBeVisible();
    await expect(page.getByText("₹1,499 / 365 days")).toBeVisible();
    await expect(page.getByText("Your current plan")).toBeVisible();

    const monthly = page.getByText("Aasan Plus · Monthly").locator("xpath=ancestor::*[.//button[normalize-space()='Upgrade']][1]");
    await monthly.getByRole("button", { name: "Upgrade" }).click();
    await expect.poll(() => page.evaluate(() => (window as unknown as { __rzp?: { opened: boolean } }).__rzp?.opened ?? false)).toBe(true);
    const opts = await page.evaluate(() => (window as unknown as { __rzp: { opts: { order_id: string; amount: number; key: string } } }).__rzp.opts);
    expect(opts).toMatchObject({ order_id: "order_e2e_test", amount: 14900, key: "rzp_test_e2e" });
    expect(checkoutBody).toMatchObject({ plan: expect.stringMatching(/plus/i) });

    // Closing the modal changes nothing.
    await page.evaluate(() => (window as unknown as { __rzp: { opts: { modal: { ondismiss: () => void } } } }).__rzp.opts.modal.ondismiss());
    await expect(page.getByRole("alert")).toHaveCount(0);
    const overview = await api.get("/api/billing/");
    expect(JSON.stringify(overview.plan ?? overview.current ?? overview)).toMatch(/free/i);
  });
});
