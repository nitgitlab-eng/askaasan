import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end browser tests against a running stack:
 *   web  E2E_BASE_URL (default http://localhost:5173, Vite dev server, proxies /api and /ws)
 *   api  E2E_API_URL  (default http://127.0.0.1:8000, run with LLM_FORCE_PROVIDER=fake)
 * Specs are *.e2e.ts so Vitest never picks them up.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./e2e/specs",
  testMatch: /.*\.e2e\.ts$/,
  outputDir: "./e2e/test-results",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // One retry absorbs the dev-only SQLite "database is locked" 500s (see fixtures.ts); flaky tests show up in the report.
  retries: Number(process.env.E2E_RETRIES ?? 1),
  // The API throttles sign-ups/logins per IP (20/min); a few workers keep the wait bounded.
  workers: Number(process.env.E2E_WORKERS ?? 3),
  reporter: [["list"], ["html", { outputFolder: "./e2e/report", open: "never" }]],
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    // Live Class / voice: a fake mic and camera, auto-allowed (headless has no real devices or permission prompt).
    permissions: ["microphone", "camera"],
    launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] },
  },
  projects: [
    // Real-UI sign-up/sign-in first, while the per-IP auth throttle is still mostly unused.
    { name: "auth", testMatch: /auth\.e2e\.ts$/, use: { ...devices["Desktop Chrome"] } },
    { name: "app", testIgnore: /(auth|mobile)\.e2e\.ts$/, dependencies: ["auth"], use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", testMatch: /mobile\.e2e\.ts$/, dependencies: ["auth"], use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
});
