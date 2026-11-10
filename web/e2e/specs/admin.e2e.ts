import { expect, test } from "../fixtures";

const SECTIONS = [
  ["/admin/overview", "Overview"],
  ["/admin/system", "System check"],
  ["/admin/providers", "AI & Voice providers"],
  ["/admin/catalog", "Catalog & creators"],
  ["/admin/payments", "Payments & plans"],
  ["/admin/calendar-apps", "Calendar apps"],
  ["/admin/workshops", "Workshops"],
  ["/admin/codes", "Promo, redeem & invoices"],
  ["/admin/support", "Support & help"],
  ["/admin/email", "Email (SMTP)"],
  ["/admin/site", "Site & legal"],
  ["/admin/users", "Users"],
  ["/admin/orgs", "Organisations"],
  ["/admin/certificates", "Certificates"],
  ["/admin/refunds", "Refunds"],
  ["/admin/staff", "Staff & audit log"],
] as const;

test.describe("admin console", () => {
  test.use({ auth: "staff" });

  test("every admin page loads for a staff user", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/admin");
    await expect(page).toHaveURL(/\/admin\/overview$/);
    await expect(page.getByText("Aasan Admin")).toBeVisible();
    for (const [path, label] of SECTIONS) {
      await page.getByRole("navigation", { name: "Admin" }).getByRole("link", { name: label }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expect(page.getByText("Something went wrong")).toHaveCount(0);
    }
  });

  test("a learner can't open the admin console", async ({ browser }) => {
    const { newLearner, signedInPage } = await import("../fixtures");
    const { page, context } = await signedInPage(browser, await newLearner());
    await page.goto("/admin/overview");
    await expect(page).toHaveURL(/\/$/); // bounced to Home
    await context.close();
  });
});
