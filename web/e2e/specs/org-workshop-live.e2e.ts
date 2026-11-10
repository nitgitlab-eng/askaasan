import { expect, newLearner, signedInPage, staffCredentials, test } from "../fixtures";
import { Api, loginUser } from "../helpers/api";
import { createOrg, inviteAndAccept } from "../helpers/org";
import { makeRunLive } from "../helpers/workshops";

test.describe("org workshop live dashboard", () => {
  test("the school sees its learner join, get ready and raise a hand, live", async ({ page, api, browser }) => {
    test.setTimeout(180_000);
    // Setup through the API: an org with one learner, workshops switched on by Aasan staff, a run for "Everyone".
    const org = await createOrg(api);
    const learner = await newLearner("Live Learner");
    const learnerApi = await Api.as(learner);
    await inviteAndAccept(api, org.slug, learner, learnerApi);
    const { email, password } = staffCredentials();
    const staff = await Api.as(await loginUser(email, password));
    const orgInfo = await api.get(`/api/orgs/${org.slug}/`);
    await staff.patch(`/api/admin/workshops/orgs/${orgInfo.id}/`, { workshops: true, workshop_seats: 10 });
    const groups = await api.get(`/api/orgs/${org.slug}/groups/`);
    const everyone = (Array.isArray(groups) ? groups : groups.results)[0].id;
    const run = await api.post(`/api/orgs/${org.slug}/workshops/runs/`, {
      workshop_slug: "quick-check",
      starts_at: new Date(Date.now() + 5 * 60_000).toISOString(),
      groups: [everyone],
      cohorts: [],
    });
    makeRunLive(run.id);

    // The cockpit's Workshops tab links to the live dashboard.
    await page.goto(`/org/${org.slug}`);
    await page.getByRole("tab", { name: "Workshops" }).click();
    await page.getByRole("link", { name: "Open live dashboard" }).first().click();
    await expect(page).toHaveURL(new RegExp(`/org/${org.slug}/workshops/${run.id}/live$`));
    await expect(page.getByRole("heading", { name: "Quick Check: What AI Really Does", level: 1 })).toBeVisible();
    await expect(page.getByText("Live", { exact: true })).toBeVisible(); // the dashboard socket is connected
    await expect(page.getByText("No one has joined yet. Tiles appear as learners open the workshop.")).toBeVisible();
    await expect(page.getByText(/Enrolled, not joined yet\s*\(1\)/)).toBeVisible();

    // The learner joins from their own browser and starts.
    const other = await signedInPage(browser, learner);
    await other.page.goto(`/workshops/${run.id}/lobby`);
    await other.page.getByRole("button", { name: "Join now" }).click();
    await expect(other.page.getByRole("heading", { name: "Before we start" })).toBeVisible();
    await expect(page.getByText("Live Learner").first()).toBeVisible({ timeout: 30_000 }); // a tile appears live
    for (const name of [/A free AI chat tool/, /10 quiet minutes/]) {
      await other.page.getByRole("checkbox", { name }).click();
      await expect(other.page.getByRole("checkbox", { name })).toBeChecked();
    }
    await other.page.getByRole("button", { name: "I'm ready, start" }).click();
    await other.page.getByRole("button", { name: "Workshop menu" }).click();
    await expect(other.page.getByRole("button", { name: "Raise hand" })).toBeEnabled({ timeout: 30_000 });
    await other.page.getByRole("button", { name: "Raise hand" }).click();

    await expect(page.getByText("1 hand raised")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("1 learner", { exact: true })).toBeVisible();
    await other.context.close();
  });
});
