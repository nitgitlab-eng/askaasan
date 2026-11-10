# Release 1.1.0 validation record (2026-10-24)

What was checked before tagging `v1.1.0`, how, and what it found. 1.1.0 adds the features chosen from a Duolingo / Schole.ai comparison: push notifications, streak repair, win-back emails, family plan and gifts, class and school leaderboards, "Ask about your organisation", training records, API keys and webhooks, and organisation SSO.

## How it was built

Three parallel branches (retention; family plan and gifts; business customers), merged into `feature/growth-b2b`. Merge work: two clashing migration numbers were re-sequenced (`billing/0012_promo_purpose`, `accounts/0011_sso`), shared files (i18n, cockpit, account page, deploy notes) kept both sides, and the 7 machine locales were deep-merged then translated once (343 strings per language, all placeholders intact).

## Automated checks (final tree)

| Check | Result |
|---|---|
| Backend pytest, SQLite | 1824 passed, 6 skipped |
| Backend pytest, Postgres 16 | 1830 passed |
| ruff check + format, `makemigrations --check` | clean |
| `check --deploy --fail-level WARNING` (CI settings) | clean |
| Migrations from an empty database | apply cleanly |
| Web vitest | 589 passed (105 files) |
| Web lint, `tsc -b` + build, e2e type-check | clean |
| Extension node:test | 15 passed |
| Playwright (23 specs incl. the new `growth.e2e.ts`) | 49 passed, no retries |

New Playwright coverage: family invite accepted from the link, organisation sign-in hidden until configured, leaderboard scope tabs and the cockpit class board, push card states (blocked by the browser / not asked yet).

## Issues found and fixed during validation

- **Sign-in config shape (cross-branch).** `/api/users/auth-config/` gained an `sso` flag; the existing Google spec asserted the exact old payload. Spec updated.
- **Admin → Payments scrolled sideways** (2386 px in a 1470 px window): the Razorpay webhook event list rendered as one unbreakable word. Present since 1.0.0; fixed.
- **"1 groups · 2 people in families"** on Admin → Families & gifts: reworded to label/number pairs in every language.
- **Environment, not code:** after a Mac reboot, Docker Desktop could not download from PyPI's file host (other hosts worked), so the API image failed to build; a Docker Desktop restart fixed it.

## Live walkthrough on the Docker stack (http://localhost:8080, Postgres, real AI)

All nine new migrations applied to the existing data.

- **Streak repair**: a 6-day streak lapsed 3 days showed the banner (free 3-lesson revival or 300 coins); coin repair restored 6 days, debited 300 coins once, banner closed · working
- **Family plan**: created in Admin → Payments → "Add a plan" (4 people, ₹299/30 days), granted to the demo teacher; invite sent from Plans; the real email arrived in Mailpit from the admin-configured sender with a 32-character link and a 6-character code; the learner joined from the link and sees "You're on கவ்யா's family plan" with her limits · working
- **Gift a plan**: gift dialog → Razorpay test checkout opened at ₹149 with the gift attached to the order (checkout was closed without paying because Razorpay showed a saved real phone number); the capture step was then run on the server twice: paid once, one code valid a year, recipient email with the message and a `/plans?code=` link, buyer receipt and GST invoice "Gift: Aasan Plus · Monthly"; the link pre-filled the code and redeeming it gave the plan · working
- **Admin → Families & gifts**: the family (2 of 4) and the redeemed gift (code shown as its last 4 characters) · working
- **Ask about your organisation**: "Which class is behind on assignments?" answered by the real AI with "Assignment completion by class" · working
- **API keys**: key shown once; members, assignments, certificates and training records answered 200; no key / wrong key 401; a write without the scope 403; after revoking, 401 · working
- **Webhooks**: an `http://` address is blocked in the form; `https://127.0.0.1/…` refused by the server ("use a host name, not an IP address") · working
- **Training records**: backfill created 6 records with certificates (run twice: 6, then 0); CSV, Excel and PDF exports answered 200 with every column · working
- **SSO**: gmail.com refused as a domain; a demo domain added with its `aasan-verify=` TXT instruction; Verify answered "We couldn't find the TXT record yet" · working (a real sign-in needs an organisation's own Google or Microsoft app)
- **Leaderboards**: Everyone / Aasan Demo School tabs, the school tab lists only members, the URL keeps the scope; the cockpit class board shows the week and "No XP earned in this class yet this week" · working
- **Win-back**: a learner away 7 days got "Meena, it's been a week…" with the streak-repair and lesson links and one-click unsubscribe; a second run sent nothing · working
- **Push**: with VAPID keys set, the Account card offers "Turn on notifications" in a real Chrome (permission not yet asked, service worker active). The browser permission prompt was not accepted on the owner's browser; delivery is covered by `test_push.py` · ready
- **Tamil**: the family panel and the push card render in Tamil · working

## Not in 1.1.0, by decision

Hearts/energy limits, daily or friend quests, a separate mistakes screen, A/B testing, WhatsApp/SMS, SCORM/LTI/HRIS connectors. Today, Review and the weak-spot drill already cover the learning side of those; the integrations wait for a customer who needs them.

## Owner steps after deploy

See `CHANGELOG.md` → 1.1.0 → "Owner setup after deploy".
