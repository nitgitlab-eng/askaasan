import { expect, test } from "../fixtures";

test.describe("paths, skills and careers", () => {
  test("join a learning path and start its first step as a course", async ({ page, api }) => {
    await page.goto("/paths");
    await page.getByRole("link", { name: /AI for everyone/ }).click();
    await expect(page).toHaveURL(/\/paths\/ai-for-everyone$/);
    await page.getByRole("button", { name: "Join this path" }).click();
    await expect(page.getByRole("button", { name: "Join this path" })).toHaveCount(0);
    await page.getByRole("listitem").filter({ hasText: "What AI is (and isn't)" }).getByRole("button", { name: "Start" }).click();
    await expect(page).toHaveURL(/\/learn\/\d+$/, { timeout: 60_000 });
    const path = await api.get("/api/paths/curated/ai-for-everyone/");
    expect(JSON.stringify(path)).toContain(page.url().split("/").pop()!); // the step now points at the new course
    await page.goto("/paths");
    await expect(page.getByRole("link", { name: /AI for everyone/ }).first()).toBeVisible();
  });

  test("follow a skill; it moves to Following and survives a reload", async ({ page, api }) => {
    await page.goto("/skills");
    await expect(page.getByText("You aren't following any skills yet — add some below.")).toBeVisible();
    await page.getByRole("listitem").filter({ hasText: /^AI basics/ }).getByRole("button", { name: "Follow" }).click();
    await expect(page.getByText("You aren't following any skills yet — add some below.")).toHaveCount(0);
    await page.reload();
    await expect(page.getByText("You aren't following any skills yet — add some below.")).toHaveCount(0);
    const skills = await api.get("/api/paths/skills/");
    expect(JSON.stringify(skills)).toContain("AI basics");
  });

  test("careers: open a role, see readiness and make a 30-day plan", async ({ page }) => {
    await page.goto("/careers");
    await expect(page.getByRole("heading", { name: "Career paths", level: 1 })).toBeVisible();
    await page.getByRole("link", { name: /^Data analyst Turns business data/ }).click();
    await expect(page.getByRole("heading", { name: "Data analyst", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What this role needs" })).toBeVisible();
    await expect(page.getByRole("listitem").filter({ hasText: "SQL & databases" })).toBeVisible();
    await page.getByRole("button", { name: "Make my plan" }).click();
    await expect(page.getByText("Write your first SQL queries")).toBeVisible({ timeout: 30_000 }); // fake AI plan
    // The role ladder links to the next roles.
    await page.getByRole("link", { name: /Senior data analyst/ }).first().click();
    await expect(page.getByRole("heading", { name: "Senior data analyst", level: 1 })).toBeVisible();
  });
});
