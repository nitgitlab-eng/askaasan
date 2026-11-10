import { readFileSync } from "node:fs";

import { expect, test } from "../fixtures";
import { loginUser } from "../helpers/api";

test.describe("account and privacy", () => {
  test("download my data as JSON", async ({ page, user }) => {
    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Account & privacy" })).toBeVisible();
    await expect(page.getByText(user.email)).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download my data" }).click()]);
    expect(download.suggestedFilename()).toMatch(/^aasan-my-data-\d{4}-\d{2}-\d{2}\.json$/);
    expect(await download.failure()).toBeNull();
    const data = JSON.parse(readFileSync(await download.path(), "utf8"));
    expect(JSON.stringify(data)).toContain(user.email);
  });

  test("email preferences toggle and persist", async ({ page }) => {
    await page.goto("/account");
    const toggle = page.getByRole("switch", { name: "Workshop emails" });
    await expect(toggle).toBeChecked();
    await toggle.click();
    await expect(toggle).not.toBeChecked();
    await page.reload();
    await expect(page.getByRole("switch", { name: "Workshop emails" })).not.toBeChecked();
  });

  test("delete my account (a fresh, throwaway user): it's gone and can't sign in", async ({ page, user }) => {
    await page.goto("/account");
    const del = page.getByRole("button", { name: "Delete my account forever" });
    await expect(del).toBeDisabled();
    await page.getByRole("textbox", { name: "Type DELETE to confirm" }).fill("DELETE");
    await page.getByLabel("Password", { exact: true }).fill(user.password);
    await expect(del).toBeEnabled();
    await del.click();
    await expect(page).toHaveURL(/\/login/);
    await expect(loginUser(user.email, user.password)).rejects.toThrow(/401/);
  });
});
