import { expect, test } from "../fixtures";
import { completeLessonViaApi } from "../helpers/learn";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

test.describe("adaptive learning", () => {
  test("topic only → Kili's scenario cards → constraints → a course with my own path and skill map", async ({ page, api }) => {
    test.setTimeout(120_000);
    await page.goto("/learn");
    await page.getByLabel("What do you want to learn?").fill("AI");
    await page.getByLabel(/Tell Kili a little about you/).fill("I run a small textile shop");
    await page.getByRole("button", { name: "Show me ways to learn it" }).click();
    await expect(page.getByText("Build a WhatsApp order-reply helper for your shop")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Foundations/)).toBeVisible();

    await page.getByText("Build a WhatsApp order-reply helper for your shop").click();
    await expect(page.getByText("Your goal")).toBeVisible();
    await page.getByLabel(/What do you already know/).fill("Excel");
    await page.getByLabel("I don't want to write code").click();
    await page.getByRole("button", { name: "Build my course" }).click();

    await expect(page).toHaveURL(/\/learn\/\d+$/, { timeout: 60_000 });
    const id = Number(page.url().split("/").pop());
    const course = await api.get(`/api/learn/curriculums/${id}/`);
    expect(course.goal).toContain("WhatsApp");
    await expect(page.getByRole("heading", { name: "Your path" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: /Start/ })).toBeVisible();
    await page.getByRole("button", { name: "Show my skill map" }).click();
    await expect(page.getByText(/goal skills mastered/)).toBeVisible();
  });

  test("my own idea that is too big is split into smaller first steps", async ({ page }) => {
    await page.goto("/learn");
    await page.getByLabel("What do you want to learn?").fill("AI");
    await page.getByRole("button", { name: "Show me ways to learn it" }).click();
    await page.getByLabel("Or describe your own use case").fill("reply to my customers with AI");
    await page.getByRole("button", { name: "Check my idea" }).click();
    // the fake AI accepts it: straight to the constraints step with the cleaned-up goal
    await expect(page.getByText("Reply to customer orders with AI")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Build my course" })).toBeVisible();
  });

  test("a lesson below the pass mark asks for practice first, then the path shows it", async ({ page, api }) => {
    test.setTimeout(120_000);
    const goal = await api.post("/api/adaptive/goals/", { topic: "AI", about: "" });
    await api.post(`/api/adaptive/goals/${goal.id}/choose/`, { index: 3 });
    const c = await api.post("/api/learn/curriculums/", { goal_id: goal.id });
    let course = await api.get(`/api/learn/curriculums/${c.id}/`);
    for (let i = 0; i < 60 && course.status !== "ready"; i++) {
      await sleep(1000);
      course = await api.get(`/api/learn/curriculums/${c.id}/`);
    }
    const first = course.sections[0].subsections[0];
    await api.post(`/api/learn/subsections/${first.id}/start/`);

    await page.goto(`/learn/${c.id}/lesson/${first.id}`);
    await expect(page.getByRole("heading", { level: 1, name: first.title })).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "Finish lesson" }).click();
    await expect(page.getByRole("heading", { name: "Almost there!" })).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Back to path" }).click();
    await expect(page.getByText(/Practice/).first()).toBeVisible();
    await expect(page.getByText(/practise, then finish/)).toBeVisible();

    // A second lesson finished well is not held back.
    const second = course.sections[0].subsections[1];
    const done = await completeLessonViaApi(api, second.id);
    expect(done.passed).toBe(true);
  });
});
