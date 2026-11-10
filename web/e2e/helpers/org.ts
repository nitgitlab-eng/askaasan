import { django, verifyEmail, type Api, type TestUser } from "./api";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export const uniqueName = (prefix: string) => `${prefix} ${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)}`;

export async function createOrg(api: Api, name = uniqueName("E2E School"), kind = "school"): Promise<{ slug: string; name: string }> {
  return api.post("/api/orgs/", { name, kind });
}

/** A Creator Lab course with every lesson generated (fake AI), ready to publish or assign. */
export async function createLabCourse(api: Api, goal = "A short intro to AI for Class 11 commerce students") {
  const c = await api.post("/api/lab/courses/", { mode: "ai", goal, level: "beginner" });
  let d = await api.get(`/api/lab/courses/${c.id}/`);
  for (let i = 0; i < 60 && d.status !== "ready"; i++) {
    if (d.status === "failed") throw new Error(`lab course ${c.id} failed: ${d.error}`);
    await sleep(1000);
    d = await api.get(`/api/lab/courses/${c.id}/`);
  }
  if (d.status !== "ready") throw new Error(`lab course ${c.id} still ${d.status}`);
  for (const s of d.sections) {
    for (const l of s.subsections) {
      await api.post(`/api/lab/subsections/${l.id}/generate/`);
      for (let i = 0; i < 60; i++) {
        const sub = await api.get(`/api/lab/subsections/${l.id}/`);
        if (sub.lesson_status === "ready") break;
        if (sub.lesson_status === "failed") throw new Error(`lesson ${l.id} failed`);
        await sleep(1000);
      }
    }
  }
  return api.get(`/api/lab/courses/${c.id}/`);
}

/** Owner invites `learner` by email; the learner (inbox verified) accepts through the API. */
export async function inviteAndAccept(owner: Api, slug: string, learner: TestUser, learnerApi: Api) {
  await owner.post(`/api/orgs/${slug}/invitations/`, { emails: [learner.email] });
  verifyEmail(learner.email);
  const token = inviteToken(slug, learner.email);
  return learnerApi.post(`/api/orgs/invites/${token}/accept/`);
}

/** The emailed invitation token (the test can't open the inbox). */
export function inviteToken(slug: string, email: string) {
  return django(
    "import os\nfrom apps.orgs.models import Invitation\nprint(Invitation.objects.filter(org__slug=os.environ['E2E_ARG_SLUG'], email__iexact=os.environ['E2E_ARG_EMAIL'], accepted_at__isnull=True).latest('id').token)",
    { slug, email },
  );
}
