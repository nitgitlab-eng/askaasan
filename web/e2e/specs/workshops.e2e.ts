import { readFileSync } from "node:fs";

import type { Page } from "@playwright/test";

import { expect, test } from "../fixtures";
import type { Api } from "../helpers/api";
import { createPublicRun, makeRunLive } from "../helpers/workshops";

/** The header's progress line ("Step 2 of 3 · Do it yourself"). */
const stageLabel = (page: Page) => page.getByText(/^Step \d+ of \d+ · [A-Z]/).first();

/** Types one message in the live stage (the "Type" toggle reveals the box). Allowed mid-reply: the host stops and answers. */
async function typeSay(page: Page, text: string) {
  const box = page.getByRole("textbox", { name: "Type your answer or question…" });
  if (!(await box.isVisible())) await page.getByRole("button", { name: "Type", exact: true }).click();
  await box.fill(text);
  await page.locator("form", { has: box }).getByRole("button", { name: "Send" }).click();
  await expect(box).toHaveValue("");
}

/** The learner's position as the server sees it (stage + idea/step cursor). */
async function position(api: Api, sessionId: number) {
  const s = await api.get(`/api/workshops/sessions/${sessionId}/`);
  return `${s.stage_index}:${s.stages?.[s.stage_index]?.cursor ?? ""}:${s.status}`;
}

/**
 * The host leads: when it asks "Shall we move on?" the learner taps "Yes, next"; until then the learner answers its
 * question (typed). Stops at the stage whose kind matches, or at the final.
 */
async function moveOnUntil(page: Page, api: Api, sessionId: number, kind: RegExp) {
  const final = page.getByRole("heading", { name: "Final assessment" });
  const yes = page.getByRole("button", { name: "Yes, next" });
  const done = page.getByRole("button", { name: "I've done this" });
  for (let i = 0; i < 20; i++) {
    if (await final.isVisible()) return;
    if (kind.test((await stageLabel(page).textContent()) ?? "")) return;
    const before = await position(api, sessionId);
    await expect(yes.or(page.getByRole("group", { name: "Quick replies" })).or(done).first()).toBeVisible({ timeout: 30_000 });
    if (await yes.isVisible()) await yes.click();
    else if (await done.first().isVisible()) await done.first().click();
    else await typeSay(page, "A prompt is the instruction I give the AI, with context so the answer fits my need.");
    await expect.poll(() => position(api, sessionId), { timeout: 30_000 }).not.toBe(before).catch(() => {}); // an answer may need a second try
    await page.waitForTimeout(300); // let the UI apply the progress frame
  }
  throw new Error(`never reached ${kind}`);
}

test.describe("workshops", () => {
  test("list → detail → enrol free → lobby → prereqs + mic check → start → host leads → raise hand → Yes, next → DIY + help → final → result + certificate", async ({ page, api, user }) => {
    test.setTimeout(240_000);
    const run = await createPublicRun({ slug: "quick-check", startsInMinutes: 5 });
    const title = "Quick Check: What AI Really Does";

    // List and detail.
    await page.goto("/workshops");
    await expect(page.getByRole("heading", { name: "Workshops", level: 1 })).toBeVisible();
    await expect(page.getByRole("region", { name: "Upcoming" }).getByRole("link", { name: title }).first()).toBeVisible();
    await page.goto(`/workshops/${run.id}`);
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    await expect(page.getByRole("list", { name: "What you'll do" }).getByRole("listitem")).toHaveCount(3);

    // Enrol (free) and open the lobby before the start: a countdown.
    await page.getByRole("button", { name: "Enrol for free" }).click();
    await expect(page.getByText("You're enrolled!")).toBeVisible();
    await page.getByRole("link", { name: "Go to the lobby" }).click();
    await expect(page).toHaveURL(new RegExp(`/workshops/${run.id}/lobby$`));
    await expect(page.getByText("Lobby")).toBeVisible();
    await expect(page.getByRole("timer").first()).toBeVisible();

    // The run goes live (test clock jump) → Join now.
    makeRunLive(run.id);
    await page.reload();
    await page.getByRole("button", { name: "Join now" }).click();
    await expect(page).toHaveURL(/\/workshops\/session\/\d+$/);
    const sessionId = Number(page.url().split("/").pop());

    // Prerequisites gate the start; the mic check is optional and never blocks it.
    await expect(page.getByRole("heading", { name: "Before we start" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Say hello to/ })).toBeVisible();
    const start = page.getByRole("button", { name: "I'm ready, start" });
    await expect(start).toBeDisabled();
    for (const name of [/A free AI chat tool/, /10 quiet minutes/]) {
      await page.getByRole("checkbox", { name }).click();
      await expect(page.getByRole("checkbox", { name })).toBeChecked(); // saved on the server, then shown
    }
    await expect(page.getByText("Ready: 2 of 2")).toBeVisible();
    await start.click();

    // The live stage: the host (fake AI) speaks first; one column with the big mic, no Next button.
    await expect(stageLabel(page)).toHaveText("Step 1 of 3 · Learn");
    await expect(page.getByTestId("host-caption")).toContainText("Demo mode", { timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Tap to talk" }).or(page.getByRole("button", { name: "Stop" })).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Next", exact: true })).toHaveCount(0);
    // Headless Chrome's fake microphone plays a constant tone; tap-to-talk keeps the mic closed, and we type instead.
    await typeSay(page, "AI learns patterns from lots of examples.");
    await expect(page.getByTestId("me-caption")).toContainText("AI learns patterns from lots of examples.");

    // ⋮ menu: plan, transcript, raise hand, language, hands-free.
    await page.getByRole("button", { name: "Workshop menu" }).click();
    const menu = page.getByRole("dialog", { name: "Workshop menu" });
    await expect(menu.getByRole("navigation", { name: "Workshop plan" })).toBeVisible();
    await expect(menu.getByRole("switch", { name: "Hands-free" })).toHaveAttribute("aria-checked", "false");
    await menu.getByRole("button", { name: "Raise hand" }).click();
    await expect(menu.getByRole("status").filter({ hasText: "Hand raised" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(menu).toHaveCount(0);

    // The host leads through the teach stage; the learner agrees with "Yes, next".
    await moveOnUntil(page, api, sessionId, /Do it yourself/);
    await expect(stageLabel(page)).toHaveText("Step 2 of 3 · Do it yourself");
    await page.getByRole("button", { name: "I've done this" }).first().click();
    await expect(page.getByRole("button", { name: "I've done this" })).toHaveCount(0);

    // DIY help: paste an error, get the host's explanation.
    await page.getByRole("button", { name: "Show my screen or paste the error" }).click();
    await page.getByRole("textbox", { name: "Error or log" }).fill("The chatbot says: 'I can't browse the internet'.");
    await page.getByRole("button", { name: "Get help" }).click();
    await expect(page.getByText("Kili says")).toBeVisible({ timeout: 30_000 });

    // Final assessment.
    await moveOnUntil(page, api, sessionId, /Final/);
    await expect(page.getByRole("heading", { name: "Final assessment" })).toBeVisible();
    await expect(page.getByText(/Pass mark: 60%/)).toBeVisible();
    for (const answer of ["It finds patterns in many labelled examples", "predicting a likely next word, again and again", "Check the date and the statistic with a trusted source"]) {
      await page.getByRole("radio", { name: answer }).check();
    }
    await page.getByPlaceholder("Write your answer here").fill(
      "I asked it to explain Ohm's law with a Chennai train example. I would double-check the voltage figure it quoted, because chatbots predict likely words and can state wrong numbers confidently.",
    );
    await page.getByRole("button", { name: "Submit answers" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Submit answers" }).click();

    // Result + certificate (PDF and public verify page).
    await expect(page).toHaveURL(new RegExp(`/workshops/session/${sessionId}/result$`), { timeout: 60_000 });
    await expect(page.getByText("You passed!")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Your certificate" })).toBeVisible();
    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download certificate (PDF)" }).click()]);
    expect(readFileSync(await download.path()).subarray(0, 5).toString()).toBe("%PDF-");
    const certs = await api.get("/api/credentials/");
    expect(JSON.stringify(certs)).toContain(title);
    const verifyHref = await page.getByRole("link", { name: "Open verify page" }).getAttribute("href");
    await page.goto(verifyHref!);
    await expect(page.getByText(user.name).first()).toBeVisible();
  });
});
