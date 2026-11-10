import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { API_URL } from "./helpers/env";

const here = dirname(fileURLToPath(import.meta.url));
export const STAFF_FILE = resolve(here, ".auth/staff.json");
const API_DIR = resolve(here, "../../api");

/**
 * Checks both servers answer, then makes sure an e2e-only staff account exists (for the admin console specs).
 * The generated password lives only in the gitignored e2e/.auth/ folder; it's passed to Django via env, never argv.
 */
export default async function globalSetup() {
  for (const url of [`${API_URL}/api/health/`, process.env.E2E_BASE_URL ?? "http://localhost:5173/"]) {
    let res: Response | null = null;
    for (let i = 0; i < 30 && !res?.ok; i++) { // the dev server may be mid-reload
      res = await fetch(url).catch(() => null);
      if (!res?.ok) await new Promise((r) => setTimeout(r, 2000));
    }
    if (!res?.ok) throw new Error(`e2e: ${url} is not reachable — start the API (LLM_FORCE_PROVIDER=fake) and Vite first`);
  }
  mkdirSync(dirname(STAFF_FILE), { recursive: true });
  let staff: { email: string; password: string };
  if (existsSync(STAFF_FILE)) staff = JSON.parse(readFileSync(STAFF_FILE, "utf8"));
  else {
    staff = { email: `e2e-staff-${randomBytes(4).toString("hex")}@example.com`, password: randomBytes(18).toString("base64url") };
    writeFileSync(STAFF_FILE, JSON.stringify(staff), { mode: 0o600 });
    chmodSync(STAFF_FILE, 0o600);
  }
  if (process.env.E2E_SKIP_STAFF) return;
  const script = [
    "import os",
    "from apps.accounts.models import User",
    "e, p = os.environ['E2E_STAFF_EMAIL'], os.environ['E2E_STAFF_PASSWORD']",
    "u = User.objects.filter(email=e).first() or User.objects.create_user(e, p)",
    "u.set_password(p); u.is_staff = True; u.is_superuser = True; u.email_verified = True; u.save()",
    "pr = u.profile; pr.onboarding_completed = True; pr.display_name = pr.display_name or 'E2E Staff'; pr.save()",
  ].join("\n");
  execFileSync("uv", ["run", "python", "manage.py", "shell", "--no-imports", "-c", script], {
    cwd: API_DIR,
    env: { ...process.env, E2E_STAFF_EMAIL: staff.email, E2E_STAFF_PASSWORD: staff.password },
    stdio: ["ignore", "ignore", "inherit"],
  });
}
