import { expect, test } from "../fixtures";

/** Keyboard users can jump past the navigation: Tab reveals "Skip to content", Enter lands focus on <main>. */
async function expectSkipToContent(page: import("@playwright/test").Page) {
  const link = page.getByRole("link", { name: "Skip to content" });
  await expect(link).toBeAttached();
  await expect(link).not.toBeInViewport(); // sr-only until it has focus
  await page.keyboard.press("Tab");
  await expect(link).toBeFocused();
  await expect(link).toBeVisible();
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("main");
  expect(await page.evaluate(() => document.activeElement?.tagName)).toBe("MAIN");
}

test.describe("accessibility", () => {
  test("home: Tab focuses the skip link, Enter moves focus to the main content", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading").first()).toBeVisible();
    await expectSkipToContent(page);
  });

  test.describe("signed out", () => {
    test.use({ auth: "none" });
    test("login: the skip link works before sign-in too", async ({ page }) => {
      await page.goto("/login");
      await expect(page.getByRole("heading").first()).toBeVisible();
      await expectSkipToContent(page);
    });
  });
});
