import type { Page } from "@playwright/test";

import { expect, test } from "../fixtures";
import { completeLessonViaApi, createCourse } from "../helpers/learn";

/** Answers whichever activity the review shows (types come in random order). */
async function answerCard(page: Page) {
  const main = page.getByRole("main");
  const kind = ((await main.getByText(/^Activity \d+ · /).first().textContent()) ?? "").split("· ")[1]?.trim();
  if (kind === "Quiz") await main.getByRole("radio", { name: /Maps traffic ETA/ }).click();
  else if (kind === "Fill in the blanks") await main.getByRole("textbox", { name: "Blank 1" }).fill("data");
  else if (kind === "Sort into groups") {
    for (const [item, group] of [["Spam filter", /^AI$/], ["Light switch", /^Not AI$/]] as const) {
      await main.getByRole("button", { name: item }).click();
      await main.getByRole("button", { name: group }).click();
    }
  } else if (kind === "Match pairs") {
    for (const [l, r] of [["Data", "Examples"], ["Model", "Learned pattern"]]) {
      await main.getByRole("button", { name: l, exact: true }).click();
      await main.getByRole("button", { name: r }).click();
    }
  } // "Put in order" is always answerable as shown
  await main.getByRole("radio", { name: "Sure" }).click();
  await main.getByRole("button", { name: "Check" }).click();
}

test.describe("review", () => {
  test("checkpoint quiz from the course page grades every card", async ({ page, api }) => {
    const course = await createCourse(api);
    const section = course.sections[0];
    for (const lesson of section.subsections) await completeLessonViaApi(api, lesson.id); // the checkpoint opens once a section is done
    const deck = (await api.get("/api/review/overview/")).total;
    expect(deck).toBeGreaterThan(0); // finishing a lesson put its questions in the deck

    await page.goto(`/learn/${course.id}`);
    await page.getByRole("link", { name: "Checkpoint quiz" }).click();
    await expect(page.getByRole("heading", { name: "Checkpoint quiz" })).toBeVisible();
    const total = Number((await page.getByText(/^1 \/ \d+$/).innerText()).split("/ ")[1]);
    for (let i = 1; i <= total; i++) {
      await expect(page.getByText(`${i} / ${total}`)).toBeVisible();
      await answerCard(page);
      await page.getByRole("button", { name: i === total ? "Finish" : "Next" }).click();
    }
    await expect(page.getByRole("heading", { name: "Review complete!" })).toBeVisible();
    expect((await api.get("/api/review/overview/")).reviewed_today).toBeGreaterThanOrEqual(total);
  });

  test("review hub shows the deck and an empty state for a new learner", async ({ page }) => {
    await page.goto("/review");
    await expect(page.getByRole("heading", { name: "Review", level: 1 })).toBeVisible();
    await expect(page.getByText("Finish a lesson and its questions will appear here for review.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Start review" })).toBeDisabled();
  });
});
