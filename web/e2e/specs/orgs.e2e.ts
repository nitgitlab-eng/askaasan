import { expect, gotoOneTimeLink, newLearner, signedInPage, test } from "../fixtures";
import { Api, verifyEmail } from "../helpers/api";
import { createLabCourse, inviteToken, uniqueName } from "../helpers/org";

test.describe("organizations", () => {
  test("create an org, invite a learner who joins, see them in the cockpit, assign a course", async ({ page, api, browser }) => {
    test.setTimeout(150_000);
    const name = uniqueName("E2E High School");
    await page.goto("/orgs");
    await page.getByRole("textbox", { name: "Organization name" }).fill(name);
    await page.getByRole("button", { name: "Create" }).click();
    await expect(page).toHaveURL(/\/org\/[a-z0-9-]+$/);
    const slug = page.url().split("/").pop()!;
    await expect(page.getByRole("heading", { name, level: 1 })).toBeVisible();

    // Accept the DPA from the cockpit banner.
    await page.getByRole("checkbox", { name: /I am authorised to accept/ }).check();
    await page.getByRole("button", { name: "Accept DPA" }).click();
    await expect(page.getByRole("button", { name: "Accept DPA" })).toHaveCount(0);

    // Invite a learner by email.
    const learner = await newLearner("Invited Learner");
    await page.getByRole("tab", { name: "Members" }).click();
    await page.getByRole("textbox", { name: "Email" }).fill(learner.email);
    await page.getByRole("button", { name: "Send invites" }).click();
    await expect(page.getByText(learner.email)).toBeVisible();

    // The learner opens the emailed invite link in their own browser and joins.
    verifyEmail(learner.email); // invites are accepted only by a verified inbox
    const token = inviteToken(slug, learner.email);
    const other = await signedInPage(browser, learner);
    await gotoOneTimeLink(other.page, `/invite/${token}`, other.page.getByText(`Welcome to ${name}!`));

    // The owner's cockpit lists the new member.
    await page.reload();
    await page.getByRole("tab", { name: "Members" }).click();
    await expect(page.getByText(learner.email).first()).toBeVisible();
    await expect(page.getByText("Pending invitations")).toHaveCount(0); // the invite was used
    const members = await api.get(`/api/orgs/${slug}/members/`);
    expect(JSON.stringify(members)).toContain(learner.email);

    // Assign a Creator Lab course to everyone; the learner sees it on Home.
    const course = await createLabCourse(api);
    await page.reload(); // the cockpit loaded its course list before this course existed
    await page.getByRole("tab", { name: "Assignments" }).click();
    const picker = page.getByRole("combobox", { name: "Course" });
    await expect(picker.locator("option", { hasText: course.title })).toHaveCount(1);
    await picker.selectOption(String(course.id));
    await page.getByRole("button", { name: "Assign", exact: true }).click();
    await expect(page.getByText(course.title).last()).toBeVisible();
    const mine = await (await Api.as(learner)).get("/api/orgs/me/assignments/");
    expect(JSON.stringify(mine)).toContain(course.title);
    await other.page.goto("/");
    await expect(other.page.getByText("Assigned to you")).toBeVisible();
    await expect(other.page.getByText(course.title).first()).toBeVisible();
    await other.context.close();
  });

  test("join a class with a join code", async ({ page, api }) => {
    const owner = await newLearner("Owner");
    const ownerApi = await Api.as(owner);
    const org = await ownerApi.post("/api/orgs/", { name: uniqueName("E2E Coaching"), kind: "coaching" });
    const groups = await ownerApi.get(`/api/orgs/${org.slug}/groups/`);
    const code = (Array.isArray(groups) ? groups : groups.results)[0].join_code;
    await page.goto("/orgs");
    await page.getByRole("textbox", { name: "Class code" }).fill(code);
    await page.getByRole("button", { name: "Join", exact: true }).click();
    await expect(page.getByText(`You joined ${org.name}`)).toBeVisible();
    const mine = await api.get("/api/orgs/");
    expect(mine.map((o: { slug: string }) => o.slug)).toContain(org.slug);
  });
});
