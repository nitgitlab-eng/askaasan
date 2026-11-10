import { expect, test } from "../fixtures";

test.describe("onboarding", () => {
  test.use({ auth: "fresh" });

  test("pick a companion, walk the steps, and get a first course", async ({ page, api }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/onboarding$/); // not onboarded yet → the wizard
    await expect(page.getByRole("heading", { name: "Hi! I'm your learning buddy" })).toBeVisible();

    // Step 0: companion pick is saved to preferences straight away.
    await page.getByRole("radio", { name: /Yaanai/ }).click();
    await expect(page.getByRole("radio", { name: /Yaanai/ })).toHaveAttribute("aria-checked", "true");
    await expect.poll(async () => (await api.get("/api/users/me/")).preferences.mascot.character).toBe("yaanai");

    const next = page.getByRole("button", { name: "Next", exact: true });
    await next.click(); // → language
    await expect(page.getByRole("heading", { name: "Which language feels comfortable?" })).toBeVisible();
    await next.click(); // → how to set up
    await page.getByRole("button", { name: /Pick options myself/ }).click();
    await expect(page.getByRole("heading", { name: "What do you want to learn?" })).toBeVisible();
    await page.getByRole("button", { name: /Python/ }).first().click();
    await page.getByPlaceholder("Or type your own goal…").fill("Write small Python scripts for my shop");
    await next.click(); // → work/role (optional)
    await next.click(); // → skills
    await next.click(); // → level
    await expect(page.getByRole("heading", { name: "Where are you starting from?" })).toBeVisible();
    await page.getByRole("radio", { name: "Intermediate" }).click();
    await next.click(); // → ready
    await expect(page.getByRole("heading", { name: /ready/i })).toBeVisible();
    await page.getByRole("button", { name: "Build my first course" }).click();

    // A first course is generated (fake AI) and opened; the profile is saved.
    await expect(page).toHaveURL(/\/learn\/\d+$/, { timeout: 60_000 });
    const me = await api.get("/api/users/me/");
    expect(me.profile.onboarding_completed).toBe(true);
    expect(me.profile.level).toBe("intermediate");
    expect(me.profile.domain).toBe("python");
    const courseId = Number(page.url().split("/").pop());
    const course = await api.get(`/api/learn/curriculums/${courseId}/`);
    expect(course.goal).toContain("Python scripts");
  });
});
