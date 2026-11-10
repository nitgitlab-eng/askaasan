import { django, loginUser, Api } from "./api";
import { staffCredentials } from "../fixtures";

/** A published, free public run of `slug`, scheduled a few minutes ahead (its lobby is already open). */
export async function createPublicRun(opts: { slug?: string; startsInMinutes?: number; price?: number } = {}) {
  const { email, password } = staffCredentials();
  const staff = await Api.as(await loginUser(email, password));
  const starts = new Date(Date.now() + (opts.startsInMinutes ?? 5) * 60_000).toISOString();
  const run = await staff.post("/api/admin/workshops/runs/", { workshop_slug: opts.slug ?? "quick-check", starts_at: starts, price_paise: opts.price ?? 0, capacity: 0 });
  await staff.post(`/api/admin/workshops/runs/${run.id}/publish/`);
  return run as { id: number; title?: string; workshop?: { title: string } };
}

/** Time travel for the test: the run's start moves to a minute ago, so it's live now (no waiting for the clock). */
export function makeRunLive(runId: number) {
  django(
    "import os\nfrom datetime import timedelta\nfrom django.utils import timezone\nfrom apps.workshops.models import WorkshopRun\nWorkshopRun.objects.filter(pk=int(os.environ['E2E_ARG_RUN'])).update(starts_at=timezone.now() - timedelta(minutes=1), status='live')",
    { run: runId },
  );
}
