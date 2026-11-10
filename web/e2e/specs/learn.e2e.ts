import { expect, test } from "../fixtures";
import { createCourse } from "../helpers/learn";

test.describe("learn", () => {
  test("build a course from the library form", async ({ page, api }) => {
    await page.goto("/learn");
    await expect(page.getByRole("heading", { name: "My courses" })).toBeVisible();
    await page.getByRole("button", { name: "I know exactly what I want" }).click(); // the guided wizard is the default
    await page.getByLabel("Your goal").fill("Use spreadsheets to track my shop's sales");
    await page.getByRole("button", { name: "Build my course" }).click();
    await expect(page).toHaveURL(/\/learn\/\d+$/, { timeout: 60_000 });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const id = Number(page.url().split("/").pop());
    const course = await api.get(`/api/learn/curriculums/${id}/`);
    expect(course.goal).toContain("spreadsheets");
    await page.goto("/learn");
    await expect(page.getByRole("link", { name: new RegExp(course.title) }).first()).toBeVisible();
  });

  test("lesson: answer every activity, finish, and progress is saved", async ({ page, api }) => {
    const course = await createCourse(api);
    const [first, second] = course.sections[0].subsections;
    expect(second.locked).toBe(true);

    await page.goto(`/learn/${course.id}`);
    await expect(page.getByText("0 of 3 lessons done")).toBeVisible();
    await page.getByRole("link", { name: first.title }).click();
    await expect(page.getByRole("heading", { level: 1, name: first.title })).toBeVisible({ timeout: 60_000 });

    // The activity card = the nearest ancestor of its "Activity n ·" label that holds a Check button.
    const card = (n: number) => page.getByText(new RegExp(`^Activity ${n} ·`)).locator("xpath=ancestor::*[.//button[normalize-space()='Check']][1]");
    const checked = async (n: number) => expect(page.getByText(new RegExp(`^${n} of 5 activities answered$`))).toBeVisible();

    // 1. Quiz
    await card(1).getByRole("radio", { name: /Maps traffic ETA/ }).click();
    await card(1).getByRole("button", { name: "Check" }).click();
    await checked(1);
    // 2. Fill in the blank
    await card(2).getByRole("textbox", { name: "Blank 1" }).fill("data");
    await card(2).getByRole("button", { name: "Check" }).click();
    await checked(2);
    // 3. Order: Collect data, Train model, Make predictions
    const order = card(3);
    const want = ["Collect data", "Train model", "Make predictions"];
    for (let i = 0; i < want.length; i++) {
      for (let guard = 0; guard < 5; guard++) {
        const texts = await order.getByRole("listitem").allInnerTexts();
        const at = texts.findIndex((t) => t.includes(want[i]));
        if (at <= i) break;
        await order.getByRole("listitem").nth(at).getByRole("button", { name: "Move up" }).click();
      }
    }
    await expect(order.getByRole("listitem").first()).toContainText("Collect data");
    await order.getByRole("button", { name: "Check" }).click();
    await checked(3);
    // 4. Sort: tap an item, then its group
    const sort = card(4);
    await sort.getByRole("button", { name: "Spam filter" }).click();
    await sort.getByRole("button", { name: /^AI$/ }).click();
    await sort.getByRole("button", { name: "Light switch" }).click();
    await sort.getByRole("button", { name: /^Not AI$/ }).click();
    await sort.getByRole("button", { name: "Check" }).click();
    await checked(4);
    // 5. Match pairs
    const match = card(5);
    await match.getByRole("button", { name: "Data", exact: true }).click();
    await match.getByRole("button", { name: "Examples" }).click();
    await match.getByRole("button", { name: "Model", exact: true }).click();
    await match.getByRole("button", { name: "Learned pattern" }).click();
    await match.getByRole("button", { name: "Check" }).click();

    await expect(page.getByText("5 of 5 activities answered")).toBeVisible();
    await page.getByRole("button", { name: "Finish lesson" }).click();
    await expect(page.getByRole("heading", { name: "Lesson complete!" })).toBeVisible();
    await expect(page.getByText("5 of 5 activities correct")).toBeVisible();

    // Saved on the server: lesson completed, next lesson unlocked, course progress 1/3.
    const after = await api.get(`/api/learn/curriculums/${course.id}/`);
    expect(after.progress.done).toBe(1);
    expect(after.sections[0].subsections[0].state).toBe("completed");
    expect(after.sections[0].subsections[1].locked).toBe(false);

    await page.getByRole("button", { name: "Next lesson" }).click();
    await expect(page).toHaveURL(new RegExp(`/lesson/${second.id}$`));
    await page.goto(`/learn/${course.id}`);
    await expect(page.getByText("1 of 3 lessons done")).toBeVisible();
  });
});
