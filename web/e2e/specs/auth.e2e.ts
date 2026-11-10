import { expect, test } from "../fixtures";
import { Api, completeOnboarding, django, loginUser, registerUser, strongPassword, uniqueEmail } from "../helpers/api";

test.use({ auth: "none" });

test.describe("auth", () => {
  test("register through the form lands on onboarding, signed in", async ({ page }) => {
    const email = uniqueEmail("signup");
    await page.goto("/signup");
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
    await page.getByLabel("Your name").fill("Asha Signup");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(strongPassword());
    const submit = page.getByRole("button", { name: "Sign up" });
    await expect(submit).toBeDisabled(); // terms + age are required first
    await page.getByRole("button", { name: "18 or older" }).click();
    await page.getByRole("checkbox").check();
    await submit.click();
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByRole("heading", { name: "Hi! I'm your learning buddy" })).toBeVisible();
    // The session survives a reload (refresh cookie → silent sign-in).
    await page.reload();
    await expect(page.getByRole("heading", { name: "Hi! I'm your learning buddy" })).toBeVisible();
  });

  test("duplicate email is rejected with a clear message", async ({ page }) => {
    const user = await registerUser({ tag: "dup" });
    await page.goto("/signup");
    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill(strongPassword());
    await page.getByRole("button", { name: "18 or older" }).click();
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Sign up" }).click();
    await expect(page.getByText("This email is already registered")).toBeVisible();
    await expect(page).toHaveURL(/\/signup/);
  });

  test("login, then logout ends the session", async ({ page }) => {
    const user = await registerUser({ tag: "login" });
    await completeOnboarding(await Api.as(user)); // so sign-in lands in the app, not the wizard
    await page.goto("/learn");
    await expect(page).toHaveURL(/\/login\?next=%2Flearn/);
    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(/\/learn$/); // back to where they were heading
    await page.getByRole("button", { name: "You", exact: true }).first().click(); // log out lives in the You menu
    await page.getByRole("menuitem", { name: "Log out" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: "Welcome back!" })).toBeVisible();
  });

  test("Google sign-in is hidden when not configured", async ({ page }) => {
    // The dev API has no GOOGLE_CLIENT_ID, so the page must not show a Google button, a stray divider or load GIS.
    const config = page.waitForResponse((r) => r.url().endsWith("/api/users/auth-config/"));
    await page.goto("/login");
    expect(await (await config).json()).toEqual({ google_client_id: "", sso: false });
    await expect(page.getByRole("button", { name: "Sign in with a passkey" })).toBeVisible();
    await expect(page.getByTestId("google-signin")).toHaveCount(0);
    await expect(page.getByText("Continue with Google")).toHaveCount(0);
    await expect(page.locator('script[src*="accounts.google.com"]')).toHaveCount(0);
    await expect(page.getByText("or", { exact: true })).toHaveCount(1); // only the password/passkey divider
    await page.goto("/signup");
    await expect(page.getByRole("heading", { name: "Create your account" })).toBeVisible();
    await expect(page.getByTestId("google-signin")).toHaveCount(0);
    await expect(page.getByText("or", { exact: true })).toHaveCount(0);
  });

  test("wrong password shows an error and stays on login", async ({ page }) => {
    const user = await registerUser({ tag: "wrongpw" });
    await page.goto("/login");
    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill("not-the-password-123");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("alert")).toHaveText("Wrong email or password");
    await expect(page).toHaveURL(/\/login/);
  });

  test("password reset: request a link, set a new password, sign in with it", async ({ page }) => {
    const user = await registerUser({ tag: "reset" });
    await page.goto("/login");
    await page.getByRole("link", { name: "Forgot password?" }).click();
    await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
    await page.getByLabel("Email").fill(user.email);
    await page.getByRole("button", { name: "Send code" }).click();
    await expect(page.getByText("If an account exists")).toBeVisible();
    await expect(page.getByLabel("6-digit code")).toBeVisible();

    // The same mail also carries a link with a one-time token; read it from the DB (the test can't open the inbox).
    const token = django(
      "import os\nfrom apps.accounts.models import OneTimeToken\nprint(OneTimeToken.objects.filter(user__email=os.environ['E2E_ARG_EMAIL'], purpose='reset_password', used_at__isnull=True).latest('id').token)",
      { email: user.email },
    );
    expect(token.length).toBeGreaterThan(20);
    const fresh = strongPassword();
    await page.goto(`/reset-password?token=${encodeURIComponent(token)}`);
    await page.getByLabel("New password").fill(fresh);
    await page.getByRole("button", { name: "Save & sign in" }).click();
    await expect(page).toHaveURL(/\/onboarding$/); // signed in (not onboarded yet)

    // The new password signs in; the old one doesn't.
    await expect((await loginUser(user.email, fresh)).access).toBeTruthy();
    await expect(loginUser(user.email, user.password)).rejects.toThrow(/401/);
  });
});
