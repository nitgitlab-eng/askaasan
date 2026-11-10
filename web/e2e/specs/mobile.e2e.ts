import { expect, expectNoHorizontalOverflow, test } from "../fixtures";
import { createCourse } from "../helpers/learn";

const PAGES = ["/", "/today", "/learn", "/review", "/paths", "/paths/ai-for-everyone", "/skills", "/careers", "/careers/data-analyst", "/mentor", "/roleplay", "/live", "/workshops", "/certificates", "/plans", "/account", "/orgs", "/personalize", "/progress", "/help"];

test.describe("mobile 390px smoke", () => {
  test("key signed-in pages fit the screen (no sideways scroll) and load cleanly", async ({ page, api }) => {
    test.setTimeout(240_000);
    const course = await createCourse(api);
    const lesson = course.sections[0].subsections[0];
    for (const path of [...PAGES, `/learn/${course.id}`, `/learn/${course.id}/lesson/${lesson.id}`]) {
      await page.goto(path);
      await expect(page.locator("main").first()).toBeVisible();
      await expect(page.getByRole("heading").first()).toBeVisible();
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await expectNoHorizontalOverflow(page);
    }
  });

  test("phones get a bottom bar with the five sections and a You menu", async ({ page }) => {
    await page.goto("/");
    const bar = page.getByRole("navigation", { name: "Main menu" }).last();
    await expect(bar).toBeVisible();
    for (const name of ["Home", "Learn", "Practice", "Progress", "Certificates"]) await expect(bar.getByRole("link", { name })).toBeVisible();
    await bar.getByRole("link", { name: "Learn" }).click();
    await expect(page).toHaveURL(/\/learn$/);
    await page.getByRole("navigation", { name: "Learn pages" }).getByRole("link", { name: "Catalog" }).click();
    await expect(page).toHaveURL(/\/catalog$/);
    await page.getByRole("button", { name: "You", exact: true }).last().click();
    await page.getByRole("menuitem", { name: /Account/ }).click();
    await expect(page).toHaveURL(/\/account$/);
    await expectNoHorizontalOverflow(page);
  });

  test.describe("signed out", () => {
    test.use({ auth: "none" });
    test("auth and legal pages fit the screen", async ({ page }) => {
      for (const path of ["/login", "/signup", "/forgot-password", "/privacy", "/terms"]) {
        await page.goto(path);
        await expect(page.getByRole("heading").first()).toBeVisible();
        await expectNoHorizontalOverflow(page);
      }
    });
  });
});
