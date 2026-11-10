import { expect, test } from "../fixtures";

test.describe("role-play", () => {
  test("start a ready-made scenario, reply twice, finish and get coaching feedback", async ({ page, api }) => {
    await page.goto("/roleplay");
    await expect(page.getByRole("heading", { name: "Role-play studio" })).toBeVisible();
    await page.getByRole("heading", { name: "Ask your teacher for help", level: 3 })
      .locator("xpath=ancestor::*[.//button[normalize-space()='Start']][1]").getByRole("button", { name: "Start" }).click();
    await expect(page).toHaveURL(/\/roleplay\/\d+$/);
    const finish = page.getByRole("button", { name: "Finish & get feedback" });
    await expect(finish).toBeDisabled(); // needs 2 replies first

    await expect(page.getByText("Mr. Senthil").first()).toBeVisible();
    const box = page.getByRole("textbox", { name: "Your reply" });
    const send = page.locator("form", { has: box }).getByRole("button", { name: "Send" });
    for (const line of ["Sir, I didn't understand today's quadratic equations topic.", "Could you explain the factoring step again, please?"]) {
      await box.fill(line);
      await expect(send).toBeEnabled({ timeout: 30_000 }); // the character's socket is connected and idle
      await send.click();
      await expect(page.getByText(line)).toBeVisible();
      await expect(box).toHaveValue("");
    }
    await expect(finish).toBeEnabled({ timeout: 30_000 });
    await finish.click();
    await expect(page.getByRole("heading", { name: "Your coaching report" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("What went well")).toBeVisible();
    const id = Number(new URL(page.url()).pathname.split("/").pop());
    const session = await api.get(`/api/roleplay/sessions/${id}/`);
    expect(session.status ?? session.state).toMatch(/ended|completed|done|finished/);
    expect(JSON.stringify(session)).toContain("factoring step"); // the learner's turns were saved with the session
  });
});
