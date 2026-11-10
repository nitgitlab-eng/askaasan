import { expect, test } from "../fixtures";
import { newLearner } from "../fixtures";

test.describe("admin console: people, certificates, audit", () => {
  test.use({ auth: "staff" });

  test("find a learner, sign them out everywhere, and see it in the audit log", async ({ page }) => {
    test.setTimeout(90_000);
    const learner = await newLearner();
    await page.goto("/admin/users");
    await page.getByLabel("Search users").fill(learner.email);
    await page.getByRole("button", { name: "Search" }).click();
    await page.getByText(learner.email).click();
    const drawer = page.getByRole("dialog", { name: "User details" });
    await expect(drawer.getByText("Plans", { exact: true })).toBeVisible();
    await drawer.getByRole("button", { name: "Sign out everywhere" }).click();
    await page.getByRole("button", { name: "OK" }).click();
    await expect(drawer.getByRole("status")).toHaveText("Signed out of every device.");
    await page.goto("/admin/staff");
    await page.getByLabel("Search audit log").fill("users");
    await page.getByRole("button", { name: "Search" }).click();
    await expect(page.getByText(/POST \/api\/admin\/users\/\d+\/action\//).first()).toBeVisible();
  });

  test("design a certificate and preview it as a PDF", async ({ page }) => {
    await page.goto("/admin/certificates");
    await page.getByRole("tab", { name: "Design (templates)" }).click();
    await page.getByLabel("Layout").selectOption("modern");
    await page.getByLabel("Signatory").fill("E2E Director");
    await page.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByTitle("Certificate preview")).toBeVisible({ timeout: 30_000 });
  });

  test("organisations and refunds pages answer", async ({ page }) => {
    await page.goto("/admin/orgs");
    await expect(page.getByRole("heading", { name: "Organisations" })).toBeVisible();
    await expect(page.getByText(/results?$/).first()).toBeVisible();
    await page.goto("/admin/refunds");
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  });
});
