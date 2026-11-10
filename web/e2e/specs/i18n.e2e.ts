import { expect, test } from "../fixtures";

test.describe("i18n", () => {
  test("switch the app to Tamil from Personalize; it sticks after a reload", async ({ page, api }) => {
    await page.goto("/personalize");
    await page.getByRole("combobox", { name: "App language" }).selectOption("ta");
    const nav = page.getByRole("navigation").first();
    await expect(nav.getByRole("link", { name: "முகப்பு" })).toBeVisible(); // "Home"
    await expect(nav.getByRole("link", { name: "கற்றல்" })).toBeVisible(); // "Learn"
    await expect.poll(async () => (await api.get("/api/users/me/")).profile.language).toBe("ta");
    await page.reload();
    await expect(page.getByRole("navigation").first().getByRole("link", { name: "முகப்பு" })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("lang", "ta");
  });

  test.describe("signed out", () => {
    test.use({ auth: "none" });
    test("the sign-in page switches to Tamil", async ({ page }) => {
      await page.goto("/login");
      await expect(page.getByRole("heading", { name: "Welcome back!" })).toBeVisible();
      await page.getByRole("combobox").first().selectOption("ta");
      await expect(page.getByRole("heading", { name: "மீண்டும் வருக!" })).toBeVisible();
    });
  });
});
