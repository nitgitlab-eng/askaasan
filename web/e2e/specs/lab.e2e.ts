import { expect, test } from "../fixtures";
import { createOrg } from "../helpers/org";

test.describe("Creator Lab", () => {
  test("create a course with an AI outline, add a lesson, generate it and publish by link", async ({ page, api }) => {
    await createOrg(api); // a school owner can author courses
    await page.goto("/lab");
    await expect(page.getByRole("heading", { name: "Creator Lab", level: 1 })).toBeVisible();
    await page.getByRole("textbox", { name: "Course brief" }).fill("A short intro to AI for Class 11 commerce students");
    await page.getByRole("button", { name: "Create course" }).click();
    await expect(page).toHaveURL(/\/lab\/\d+$/, { timeout: 60_000 });
    const id = Number(page.url().split("/").pop());
    await expect(page.getByRole("textbox", { name: "Title" })).toHaveValue(/\S/, { timeout: 60_000 });

    // Add a lesson to the first section through the in-app dialog.
    await page.getByRole("button", { name: "Add lesson" }).first().click();
    const dialog = page.getByRole("dialog");
    await dialog.getByRole("textbox").fill("Spotting AI at home");
    await dialog.getByRole("button", { name: "OK" }).click();
    await page.getByRole("button", { name: "Spotting AI at home" }).click();
    await page.getByRole("button", { name: "Generate lesson with AI" }).click();
    await expect(page.getByRole("button", { name: "Regenerate" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByRole("heading", { name: "Lesson text" })).toBeVisible();

    let course = await api.get(`/api/lab/courses/${id}/`);
    const added = course.sections[0].subsections.find((l: { title: string }) => l.title === "Spotting AI at home");
    expect(added?.lesson_status).toBe("ready");
    expect(added?.activities).toBeGreaterThan(0);

    // Publishing needs every lesson ready: generate the rest through the API, then share by link in the UI.
    for (const s of course.sections) for (const l of s.subsections) if (l.lesson_status !== "ready") await api.post(`/api/lab/subsections/${l.id}/generate/`);
    await expect.poll(async () => (await api.get(`/api/lab/courses/${id}/`)).sections.flatMap((s: any) => s.subsections).every((l: any) => l.lesson_status === "ready"), { timeout: 60_000 }).toBe(true);
    await page.reload();
    await page.getByRole("button", { name: /^Link Anyone with the link/ }).click();
    await expect(page.getByRole("button", { name: /^Link Anyone with the link/ })).toHaveAttribute("aria-pressed", "true");
    course = await api.get(`/api/lab/courses/${id}/`);
    expect(course.visibility).toBe("link");
    expect(course.published_at).toBeTruthy();
  });
});
