import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { test as base, expect, type Browser, type BrowserContext, type Page } from "@playwright/test";

import { Api, completeOnboarding, loginUser, registerUser, type TestUser } from "./helpers/api";
import { BASE_URL } from "./helpers/env";

export { expect };
export type { TestUser };

type AuthMode = "learner" | "fresh" | "staff" | "none";

/** Console noise that isn't an app bug (expected 4xx answers the UI handles, dev-only warnings). */
const ALLOWED_CONSOLE = [
  /Failed to load resource: the server responded with a status of 4\d\d/,
  /Download the React DevTools/,
  /\[vite\]/,
];

function storageFor(user: TestUser) {
  const host = new URL(BASE_URL).hostname;
  return {
    cookies: [{ name: "aasan_refresh", value: user.refresh, domain: host, path: "/api/users/", expires: Math.floor(Date.now() / 1000) + 86400, httpOnly: true, secure: false, sameSite: "Strict" as const }],
    origins: [{ origin: new URL(BASE_URL).origin, localStorage: [
      { name: "aasan-auth", value: JSON.stringify({ state: { signedIn: true, legacyRefresh: null }, version: 1 }) },
      { name: "aasan-lang", value: "en" },
      { name: "aasan-storage-notice", value: "1" },
    ] }],
  };
}

/**
 * Local dev runs the API on SQLite, which answers "database is locked" (HTTP 500) when a background job and a request
 * write at the same moment. That's an environment limit (Postgres in production), not an app bug, so those 500s are
 * noted on the test instead of failing it. Set E2E_STRICT_DB=1 to fail on them too.
 */
const SQLITE_LOCK = /database is locked/;

/** Attaches the console/pageerror guard; `assertClean()` runs at the end of every test using the `page` fixture. */
export function guardConsole(page: Page) {
  const errors: string[] = [];
  const allowed = [...ALLOWED_CONSOLE];
  const pending: Promise<void>[] = [];
  let lockHits = 0;
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (!allowed.some((re) => re.test(text))) errors.push(`console.error: ${text}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  // Server errors are bugs even when the UI copes; name the endpoint so the report is actionable.
  page.on("response", (res) => {
    if (res.status() < 500) return;
    pending.push(
      res.text().catch(() => "").then((body) => {
        if (SQLITE_LOCK.test(body) && !process.env.E2E_STRICT_DB) lockHits++;
        else errors.push(`HTTP ${res.status()} ${res.request().method()} ${res.url()}`);
      }),
    );
  });
  return {
    errors,
    allow: (re: RegExp) => void allowed.push(re),
    assertClean: async () => {
      await Promise.all(pending);
      // The browser logs the 500 it got; drop those lines when every 500 was a SQLite lock.
      const real = lockHits && !errors.some((e) => e.startsWith("HTTP 5")) ? errors.filter((e) => !/status of 500/.test(e)) : errors;
      if (lockHits) test.info().annotations.push({ type: "sqlite-lock", description: `${lockHits} HTTP 500 "database is locked" (dev SQLite)` });
      expect(real, "unexpected console errors").toEqual([]);
    },
  };
}

/** A fresh, onboarded learner (registered through the real API). */
export async function newLearner(name?: string): Promise<TestUser> {
  const user = await registerUser({ name });
  await completeOnboarding(await Api.as(user));
  return user;
}

export function staffCredentials(): { email: string; password: string } {
  return JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), ".auth/staff.json"), "utf8"));
}

/** Opens a second, independently signed-in browser (e.g. the invitee in an org flow). */
export async function signedInPage(browser: Browser, user: TestUser, options: Parameters<Browser["newContext"]>[0] = {}): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ ...options, baseURL: BASE_URL, storageState: storageFor(user) });
  const page = await context.newPage();
  return { context, page };
}

export const test = base.extend<{ auth: AuthMode; user: TestUser; api: Api }>({
  auth: ["learner", { option: true }],
  user: async ({ auth }, provide) => {
    if (auth === "none") return provide(null as unknown as TestUser);
    if (auth === "staff") {
      const { email, password } = staffCredentials();
      const staff = await loginUser(email, password);
      await (await Api.as(staff)).patch("/api/users/preferences/", { learning: { tours_done: ["app", "lab", "cockpit", "admin"] } });
      return provide(staff);
    }
    const user = await registerUser();
    if (auth === "learner") await completeOnboarding(await Api.as(user));
    else await (await Api.as(user)).patch("/api/users/preferences/", { learning: { tours_done: ["app", "lab", "cockpit", "admin"] } });
    await provide(user);
  },
  api: async ({ user }, provide) => {
    await provide(user ? await Api.as(user) : (null as unknown as Api));
  },
  storageState: async ({ auth, user }, provide) => {
    await provide(auth === "none" ? { cookies: [], origins: [] } : storageFor(user));
  },
  page: async ({ page }, provide) => {
    const guard = guardConsole(page);
    (page as Page & { __guard?: typeof guard }).__guard = guard;
    await provide(page);
    await guard.assertClean();
  },
});

/** Allow a console message pattern for the current test's page (known, harmless noise). */
export function allowConsole(page: Page, re: RegExp) {
  (page as Page & { __guard?: ReturnType<typeof guardConsole> }).__guard?.allow(re);
}

/** No element wider than the viewport (horizontal scroll) — used by the mobile smoke run. */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `page ${page.url()} scrolls horizontally by ${overflow}px`).toBeLessThanOrEqual(1);
}

/**
 * Opens a page whose first request is a one-time write (accept an invite, join by link). On the dev SQLite API that
 * write can lose a lock race with the page's other startup requests and answer 500 (rolled back, so the link still
 * works); reload up to twice in that case. With E2E_STRICT_DB=1 there's no second chance.
 */
export async function gotoOneTimeLink(page: Page, url: string, success: ReturnType<Page["getByText"]>) {
  const failed = page.getByText("Something went wrong. Please try again.");
  await page.goto(url);
  for (let i = 0; i < (process.env.E2E_STRICT_DB ? 0 : 2); i++) {
    await expect(success.or(failed).first()).toBeVisible();
    if (!(await failed.isVisible())) break;
    await page.reload();
  }
  await expect(success).toBeVisible();
}
