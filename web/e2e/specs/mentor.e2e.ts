import { expect, test } from "../fixtures";

test.describe("mentor chat", () => {
  test("ask a question and the (fake) AI reply streams in; the chat is saved", async ({ page, api }) => {
    await page.goto("/mentor");
    await expect(page.getByRole("heading", { name: "Ask Aasan", level: 1 })).toBeVisible();
    const box = page.getByRole("textbox", { name: "Type your question…" });
    await box.fill("Explain machine learning with a cricket example");
    await page.getByRole("main").locator("form", { has: box }).getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Explain machine learning with a cricket example")).toBeVisible();
    await expect(page.getByText("Demo mode")).toBeVisible({ timeout: 30_000 });
    await expect(box).toBeEnabled();

    // Follow-up in the same conversation, then it's listed and reopens with both turns.
    await box.fill("And a second question?");
    await page.getByRole("main").locator("form", { has: box }).getByRole("button", { name: "Send" }).click();
    await expect(page.getByText("Demo mode")).toHaveCount(2, { timeout: 30_000 });
    const convs = await api.get("/api/assistant/conversations/");
    const list = Array.isArray(convs) ? convs : convs.results;
    expect(list.length).toBe(1);
    await page.goto(`/mentor/${list[0].id}`);
    await expect(page.getByText("And a second question?")).toBeVisible();
    await expect(page.getByText("Demo mode")).toHaveCount(2);
  });
});
