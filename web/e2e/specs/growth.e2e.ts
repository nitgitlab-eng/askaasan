import { expect, newLearner, signedInPage, test } from "../fixtures";
import { Api, django, verifyEmail } from "../helpers/api";
import { createOrg, uniqueName } from "../helpers/org";

/** A paid family plan for `email`, granted through the same server path as an admin grant (no payment involved). */
function grantFamilyPlan(email: string): string {
  return django(
    `import os
from apps.accounts.models import User
from apps.billing.models import Plan
from apps.billing.services import manual_grant
code = os.environ["E2E_ARG_CODE"]
plan, _ = Plan.objects.get_or_create(code=code, defaults=dict(name="Family E2E", price_paise=29900, period_days=30, family=True, max_members=3, active=False))
owner = User.objects.get(email=os.environ["E2E_ARG_EMAIL"])
manual_grant(owner, plan, 30, owner, note="e2e")
print(plan.name)`,
    { email, code: `family-e2e-${Date.now().toString(36)}` },
  );
}

/** The invite link's token is emailed and stored only as a hash; give the latest invite a token the test knows. */
function setInviteToken(email: string, token: string) {
  django(
    `import os
from apps.billing import family
from apps.billing.models import FamilyInvite
inv = FamilyInvite.objects.filter(email__iexact=os.environ["E2E_ARG_EMAIL"]).latest("id")
inv.token_hash = family.hash_secret(os.environ["E2E_ARG_TOKEN"])
inv.save(update_fields=["token_hash"])`,
    { email, token },
  );
}

test.describe("growth features", () => {
  test("family plan: the owner invites, the invitee joins from the link and gets the plan", async ({ browser, user, api }) => {
    const planName = grantFamilyPlan(user.email);
    const member = await newLearner("Family Member");
    verifyEmail(member.email);
    const invite = await api.post("/api/billing/family/invite/", { email: member.email });
    expect(invite.invite.email).toBe(member.email.toLowerCase());
    const token = `e2e${Date.now().toString(36)}abcdefghijklmnopqrstuv`;
    setInviteToken(member.email, token);

    const { context, page } = await signedInPage(browser, member);
    await page.goto(`/family/${token}`);
    await expect(page.getByText(new RegExp(`invited you to share ${planName}`))).toBeVisible();
    await page.getByRole("button", { name: "Join the family plan" }).click();
    await expect(page.getByText(/You're in!/)).toBeVisible();

    const memberApi = await Api.as(member);
    const state = await memberApi.get("/api/billing/family/");
    expect(state.role).toBe("member");
    const overview = await memberApi.get("/api/billing/");
    expect(JSON.stringify(overview)).toContain(planName);
    await page.goto("/plans");
    await expect(page.getByText(new RegExp(`family plan: ${planName}`))).toBeVisible();
    await context.close();
  });

  test("leaderboard scopes and the cockpit class board", async ({ page, api }) => {
    const org = await createOrg(api, uniqueName("Board School"));
    await api.post(`/api/orgs/${org.slug}/groups/`, { name: "7-A" });

    await page.goto("/leaderboard");
    const tabs = page.getByRole("tablist", { name: "Which leaderboard" });
    await expect(tabs.getByRole("tab", { name: "Everyone" })).toBeVisible();
    await tabs.getByRole("tab", { name: org.name }).click();
    await expect(tabs.getByRole("tab", { name: org.name })).toHaveAttribute("aria-selected", "true");
    await expect(page).toHaveURL(/scope=org/);

    await page.goto(`/org/${org.slug}`);
    await page.getByRole("tab", { name: "Classes" }).click();
    await page.getByRole("button", { name: "This week's top learners" }).first().click();
    await expect(page.getByText("No XP earned in this class yet this week.")).toBeVisible();
  });

});

test.describe("signed out", () => {
  test.use({ auth: "none" });

  test("organisation sign-in stays hidden until an organisation turns SSO on", async ({ page }) => {
    const cfg = await (await page.request.get("/api/users/auth-config/")).json();
    expect(cfg.sso).toBe(false);
    await page.goto("/login");
    await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
    await expect(page.getByText("Sign in with your organisation")).toHaveCount(0);
  });
});

test.describe("push notifications", () => {
  test("blocked by the browser: the card explains how to allow them", async ({ page, api }) => {
    test.skip(!(await api.get("/api/users/push/")).enabled, "the API has no VAPID keys");
    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Notifications on this device" })).toBeVisible();
    await expect(page.getByText(/Notifications are blocked for Aasan/)).toBeVisible();
  });

  test("not asked yet: the card offers to turn them on", async ({ page, api }) => {
    test.skip(!(await api.get("/api/users/push/")).enabled, "the API has no VAPID keys");
    // Headless Chromium always reports "denied"; a first visit in a real browser reports "default" (not asked yet).
    await page.addInitScript(() => Object.defineProperty(Notification, "permission", { get: () => "default" }));
    await page.goto("/account");
    await expect(page.getByRole("heading", { name: "Notifications on this device" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Turn on notifications" })).toBeVisible();
  });
});
