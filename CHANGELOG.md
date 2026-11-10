# Changelog

All notable changes to Aasan are recorded here. Versions follow semantic versioning; the web app, the API and the browser extension share one version number.

## 1.3.0 — 2026-11-02

Closes the go-live blockers and most pre-scale gaps from the October 2026 technical gap review. The review was
checked against the code first; items already handled (the security round being uncommitted, refresh-cookie
settings, widget sandboxing, webhook replay, Razorpay dedup, LiveKit token scope, extension store build) were left.

### Safety for children (DPDP Act)
- **Verifiable guardian consent.** An under-18's guardian gets a link to agree or refuse. Until they agree, the AI
  mentor, voice, role-play, live class, workshops and document uploads stay locked (lessons work); a banner tells the
  learner and resends the email. A new guardian address must agree afresh; a minor can't switch themselves to adult.
- **No behavioural nudges for minors:** no win-back emails or promos, evening, step-up or learned-time pushes.
- Deepgram and LiveKit Cloud (when used) now appear in the sub-processor list.

### Data
- **Retention:** mentor conversations untouched for 12 months, role-play transcripts after 12 months, AI usage rows
  after ~13 months and speech clips after 6 months are deleted nightly (`*_RETENTION_DAYS`; privacy page updated).
- **Backups:** encrypted with `age`, copied off the server (required), checksummed; `infra/restore.sh` with a
  monthly `--drill`; optional WAL-G point-in-time recovery overlay (`infra/docker-compose.pitr.yml`).

### Security
- Lockouts, OTP tries, mail caps and code-guessing budgets live in a never-evicting Redis with atomic counters.
- Staff admin changes need a passkey or an emailed code within 30 minutes (was any sign-in within 12 hours).
- Passwords found in public breaches are refused (Have I Been Pwned, k-anonymity, fails open).
- Pyodide is served from our own origin; the site CSP drops jsDelivr and `unsafe-eval`.
- Any setting can come from a file (`NAME_FILE`, for Docker secrets / secret managers). A public site refuses to
  start without `SENTRY_DSN` (or `SENTRY_OPTIONAL=1`) or with a group/world-readable `api/.env`.
- The token refresh checks the request's Origin; the readiness probe is cached and rate-limited; revoked certificates
  say "withdrawn" on the public page.

### Reliability and operations
- LLM failover (`LLM_FALLBACK`) with a circuit breaker; monthly AI spend alerts at 50/80/95% (`LLM_MONTHLY_BUDGET`).
- `/api/metrics/` (Prometheus, token-protected) and `infra/docker-compose.monitoring.yml` (Prometheus, Alertmanager,
  Grafana, Loki with 90-day logs) with alerts for queue backlog, task failures, disk, Redis, DB connections, AI
  errors and webhooks.
- Live voice call cap per host (`VOICE_LIVE_MAX_CALLS`, default 12; over it voice falls back to streamed listening).
- Migrations give up on a busy lock after 5 s; a second Celery beat refuses to start; plan, study and guardian
  reminders claim before sending, so an overlapping run can't send twice.
- `docs/INFRA-RECOMMENDATION.md`: VPS vs dedicated, sizing, go-live and owner/legal checklists.
- **CI:** gitleaks, bandit, Trivy failing on HIGH (web image now upgrades its Alpine packages), CycloneDX SBOMs,
  a 90% API coverage floor, and `DJANGO_DEBUG` set for the test jobs. Tags `v*` build and push images to GHCR
  (`release-images.yml`).
- **Deploys:** production pulls versioned images (`TAG` is now required; `TAG=dev` for local builds) instead of building
  on the host; rollback is setting the previous `TAG`. `infra/docker-compose.staging.yml` plus a release runbook.

### Owner notes
- Restart Celery beat (new jobs `data-retention`, `llm-spend`). Run `migrate` (guardian consent fields).
- Existing under-18 accounts are locked from AI features until their guardian agrees: use "Email them again".
- Set `TAG` in `infra/.env` (e.g. `TAG=latest` for the stack already running locally).
- Before go-live: Sentry DSN, `BACKUP_AGE_RECIPIENT` + `BACKUP_COPY_CMD`, `METRICS_TOKEN`, `chmod 600 api/.env`.
- Ask counsel whether an email link is "verifiable" consent for every case (see the infra recommendation).

## 1.2.0 — 2026-10-25

Duolingo-style reminders: personal, well-timed, and quieter when they aren't wanted.

### Ships
- **Companion voice.** Push and bell reminders are written in the learner's chosen companion (Kili 🦜, Yaanai 🐘, Mayil 🦚) and mentor personality (Anna/Akka, Strict teacher, Funny buddy, Calm guru), with their name, streak, course and goal, in English and Tamil. Messages rotate so the same line never comes twice in a row. Static copy, no AI calls.
- **Learned best time.** Each night Aasan works out when each learner usually starts studying (median of the first activity per day over 21 days, at least 5 days). Streak and review nudges arrive about 30 minutes before that, never between 22:00 and 08:00. A reminder time the learner set themselves always wins; Plan shows "We'll nudge you around HH:MM" when they haven't set one.
- **Step-up after a miss.** The day a streak breaks: "your streak can come back" with the repair offer. The next day: hours left to repair. Then the day-3 win-back email takes over (its push yields to the step-up). Learners without a streak get one gentle "missed yesterday" on a study day. A streak freeze still covers a single missed day.
- **Back off when ignored.** Every reminder push carries an id; tapping it (or opening the app within 6 hours) counts as opened. After 5 ignored reminders they come every other day; after 8 they pause and the learner is told once. Any lesson, any tap or "Resume" on Account brings them back. At most 2 reminder pushes a day. Teacher, workshop and plan messages are never held back.

### Owner notes
- About 96 Tamil push title/body pairs in `api/apps/accounts/voice.py` and the new Tamil UI strings should be read by a native speaker before launch.
- Restart Celery beat: new jobs `stepup-checks` (15 min) and `reminder-nightly` (03:15); `evening-checks` now runs every 15 minutes.

## 1.1.0 — 2026-10-24

Growth and business-customer features chosen from a comparison with Duolingo and Schole.ai: only the gaps with retention or revenue value were built.

### Learners: coming back
- **Push notifications** on phones and computers (installed app or browser): study reminder, streak at risk, reviews due, workshop starting, a teacher's message, plan ending. Each type can be switched off; Account → "Notifications on this device".
- **Streak repair**: within 7 days of a broken streak (2+ days), bring it back for 300 coins, or free by finishing 3 lessons or Today circuits within 72 hours. Banner on Home, Today and Achievements.
- **Win-back emails** after 3, 7 and 30 days away, with a personal line (the course in progress, the lost streak, reviews due) and the streak-repair offer; one-click unsubscribe.
- **Comeback offer** when a paid plan has lapsed for 3 to 10 days: one email with the promo code an admin marks as "Win-back email" in Admin → Codes (at most once per 180 days; codes are never sent by push).

### Learners: paying together
- **Family plan**: a plan flagged "family" is shared with up to N people (owner included). The owner invites by email (link or 6-character code, stored only as hashes, 7 days, only for the invited address); renewals, grace days and refunds follow the owner automatically.
- **Gift a plan**: pay once for someone else; they get a code by email (valid a year) with your message; GST invoice to the buyer; refundable only until the code is used.

### Schools and companies
- **Class and school leaderboards**: learners switch between Everyone, their school and their class; teachers see each class's top 10 for the week in the cockpit. The school's leaderboard switch and each learner's opt-out still apply.
- **Ask about your organisation** in the cockpit: plain-language questions ("Which class is behind?") answered from a fixed set of measures; learners by first name only.
- **Training records** for audits: an append-only record of who finished what, when, with score, time and certificate; CSV, Excel and PDF from the cockpit, "My training record" for learners, and the API. `manage.py backfill_training_records` fills in past completions.
- **API keys and webhooks** (cockpit → Integrations): scoped keys for `/api/v1/orgs/<slug>/` (members, assignments, certificates, training records); signed webhooks for member joined, assignment or course completed, certificate issued, workshop passed, with retries and a delivery log.
- **Sign in with your organisation (SSO)**: Google Workspace or Microsoft Entra ID per organisation, email domains proven by a DNS TXT record, automatic joining with a default role and class, optional "require SSO" with an owner break-glass.

### Fixes
- Admin → Payments no longer scrolls sideways (the Razorpay webhook event list now wraps).

### Owner setup after deploy
- `uv run python manage.py setup_env` once to add a VAPID key pair to `api/.env`, then set `WEBPUSH_VAPID_SUBJECT=mailto:support@<domain>`. Push needs HTTPS and outbound HTTPS from the worker.
- Restart Celery beat: new jobs `evening-checks`, `winback-daily`, `webhook-retries`, `webhook-cleanup`, `sso-domain-recheck`.
- Admin → Payments → "Add a plan" with "Family plan" on, then set people and limits and switch it on sale.
- Admin → Codes: create a promo marked "Win-back email" to send the comeback offer.
- `manage.py backfill_training_records` once, for records of past completions.
- Organisations that want SSO register an OAuth app with Google or Microsoft (docs/DEPLOY.md) and add the DNS TXT record shown in their cockpit.

## 1.0.0 — 2026-10-23

First production release.

### Ships
- **Learning**: onboarding interview, AI-generated courses and lessons with activities, spaced review, learning paths and careers, certificates, learner progress and streaks.
- **Adaptive learning**: goal interview → concept graph → per-learner path, with re-planning on lesson completion, checkpoints, fast-track and practice, completion gating and certificate checks.
- **Ask Aasan**: streaming mentor over WebSocket, typed and tap-to-talk, hands-free voice mode and live conversation (Deepgram or Sarvam voices when configured), Kili mascot reactions driven by the server.
- **Lesson media**: per-lesson images and lecture audio/video with admin switches, served by nginx from the media volume.
- **Role-play and live classes**: WebSocket role-play scenarios and live class rooms.
- **AI Workshops**: server-owned sessions, hidden tests and rubrics, MCP server for tools, external MCP client, institution cockpit with a live run monitor. Institution workshops are on by default; only a platform admin can switch them off per institution.
- **Creator Lab**: authoring and publishing of courses and workshops.
- **Institutions**: organisations, seats, codes, DPA acceptance, feature flags.
- **Billing**: Razorpay plans, refunds and invoices (test mode supported).
- **Accounts**: email + password with verification, passkeys, Google sign-in (button appears once `GOOGLE_CLIENT_ID` is set), referral codes, last-seen tracking, data export and deletion.
- **Admin console**: overview, users, orgs, codes, certificates, staff and roles, refunds, support, email (SMTP configurable in the console with a test mail), providers (AI, voice, with test buttons), features, site/legal pages, system check. Every admin page is translated into all 9 languages. Every admin mutation is audited.
- **Accessibility and appearance**: light, dark and "Follow my device" themes, skip-to-content link, 390 px mobile layout, 9 UI languages (English and Tamil hand-written; Hindi, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati machine-translated).
- **Browser extension** (Manifest V3): Aasan Companion with pairing codes for browser tasks.
- **Operations**: docker-compose stack (Postgres, two Redis instances, Mailpit, API, worker, beat, nginx), readiness and health endpoints, nightly backup script, CI running the API suite on SQLite and Postgres, the web suite, Playwright end-to-end, the Docker build and the extension tests.

### Owner setup after deploy
- `GOOGLE_CLIENT_ID` in `api/.env` to show the Google button (docs/DEPLOY.md, section 3).
- SMTP in Admin → Email (send the test mail before relying on it).
- `DEEPGRAM_API_KEY` (or Sarvam) in Admin → Providers for live voice conversation; without it the app falls back to hands-free browser speech.
- Razorpay live keys in Admin → Payments when leaving test mode.
- Institution seat counts per organisation (0 seats means workshop runs are refused with `quota_exceeded`).

### Not in this release (by choice)
- Object storage (S3) for media: media lives on the `mediafiles` volume, backed up nightly.
- Transactional email API providers: SMTP only.
- Continuous deployment: CI validates; deploys follow docs/DEPLOY.md by hand.
