import { expect, test } from "../fixtures";

test.describe("live class", () => {
  test("start a voice-only class, ask a typed question, get a reply, end it", async ({ page }) => {
    await page.goto("/live");
    await expect(page.getByRole("heading", { name: "Live Class", level: 1 })).toBeVisible();
    await page.getByRole("textbox", { name: "What do you want to work on?" }).fill("My Python homework on loops");
    await page.getByRole("radio", { name: /Voice only/ }).click();
    await page.getByRole("button", { name: "Start class" }).click();
    const ask = page.getByRole("textbox", { name: "Type a question…" });
    await expect(ask).toBeVisible({ timeout: 30_000 });
    await ask.fill("How does a for loop work?");
    await ask.press("Enter");
    await expect(page.getByText("Demo mode").first()).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "End class" }).click();
    await expect(page.getByRole("heading", { name: /Class complete!/ })).toBeVisible({ timeout: 30_000 });
  });
});
