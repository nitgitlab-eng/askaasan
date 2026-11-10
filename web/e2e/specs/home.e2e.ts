import { expect, test } from "../fixtures";

test.describe("home and today", () => {
  test("home greets the learner and the ask box opens a mentor chat", async ({ page, user }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: `Hello, ${user.name}!` })).toBeVisible();
    await expect(page.getByText("No conversations yet — start with a question!")).toBeVisible();
    await page.getByRole("textbox", { name: "Ask Aasan anything" }).fill("What is AI?");
    await page.getByRole("main").locator("form", { has: page.getByRole("textbox", { name: "Ask Aasan anything" }) }).getByRole("button", { name: "Send" }).click();
    await expect(page).toHaveURL(/\/mentor/);
    await expect(page.getByText("Demo mode")).toBeVisible({ timeout: 30_000 });
    await page.goto("/");
    await expect(page.getByText("No conversations yet — start with a question!")).toHaveCount(0);
  });

  test("today: mark a station done and it stays done", async ({ page, api }) => {
    await page.goto("/today");
    await expect(page.getByRole("heading", { name: "Today", level: 1 })).toBeVisible();
    const before = await api.get("/api/study/today/");
    expect(before.done).toBe(0);
    await expect(page.getByText(new RegExp(`^0 of ${before.total} stations? done$`))).toBeVisible();
    await page.getByRole("button", { name: "Mark done" }).first().click();
    const doneText = before.total === 1 ? /All done for today/ : new RegExp(`^1 of ${before.total} stations? done$`);
    await expect(page.getByText(doneText)).toBeVisible();
    await page.reload();
    await expect(page.getByText(doneText)).toBeVisible();
    expect((await api.get("/api/study/today/")).done).toBe(1);
  });
});
