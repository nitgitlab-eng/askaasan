import { readFileSync } from "node:fs";

import { expect, newLearner, test } from "../fixtures";
import { Api } from "../helpers/api";
import { completeLessonViaApi } from "../helpers/learn";
import { createLabCourse, createOrg, inviteAndAccept } from "../helpers/org";

test.describe("certificates", () => {
  test("finishing an assigned course earns a certificate with a PDF and a public verify page", async ({ page, api, user }) => {
    test.setTimeout(150_000);
    // A school assigns its course to the learner; passing every lesson earns the school's certificate.
    const owner = await Api.as(await newLearner("School Owner"));
    const org = await createOrg(owner);
    const course = await createLabCourse(owner);
    await inviteAndAccept(owner, org.slug, user, api);
    await owner.post(`/api/orgs/${org.slug}/assignments/`, { curriculum_id: course.id });
    for (const s of course.sections) for (const l of s.subsections) await completeLessonViaApi(api, l.id);

    await page.goto("/certificates");
    await expect(page.getByRole("heading", { name: "My certificates" })).toBeVisible();
    await expect(page.getByRole("heading", { name: course.title, level: 2 })).toBeVisible();

    const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "PDF" }).click()]);
    const file = await download.path();
    expect(readFileSync(file).subarray(0, 5).toString()).toBe("%PDF-");
    expect(download.suggestedFilename()).toMatch(/\.pdf$/);

    // The public verify link works without signing in.
    const certs = await api.get("/api/credentials/");
    const cert = (Array.isArray(certs) ? certs : certs.results)[0];
    const verify = await page.context().browser()!.newPage();
    await verify.goto(new URL(cert.verify_url).pathname);
    await expect(verify.getByText(course.title)).toBeVisible();
    await expect(verify.getByText(user.name)).toBeVisible();
    await verify.close();
  });
});
