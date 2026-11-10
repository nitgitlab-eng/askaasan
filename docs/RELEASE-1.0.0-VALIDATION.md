# Release 1.0.0 validation record (2026-10-23/24)

What was checked before tagging `v1.0.0`, how, and what it found. Format: area · how checked · result.

## Automated checks (final tree, commit tagged v1.0.0)

| Check | Result |
|---|---|
| Backend pytest, SQLite | 1628 passed, 6 skipped |
| Backend pytest, Postgres 16 | 1635 passed (first run: 26 failed / 21 errors, all traced to the two fixes below) |
| ruff check + ruff format | clean (577 files) |
| makemigrations --check | no changes |
| check --deploy --fail-level WARNING (prod env) | clean |
| Web tsc + vite build | ok |
| Playwright e2e type-check, oxlint | ok |
| Web vitest | 537 passed (92 files) |
| Extension node:test | 15 passed |
| Playwright e2e (22 specs, fake AI, fresh SQLite) | final run: 44 passed, no retries. First run under heavy load: 3 flaky, 2 failed → 1 real bug fixed (below), 1 load-only |
| Locale drift (en vs ta keys, plurals) | ok; 7 machine locales translated (1289 strings each), only brand names / placeholders / codes stay English |

## Bugs found by this validation (all fixed in this release)

- **Today page empty on a fresh database.** The built-in role-play scenarios were only created the first time someone listed role-play scenarios, so a new deployment showed "0 of 0 stations" until a learner happened to open role-play. The station builder now ensures the library itself (`ensure_library`, shared with the role-play API). Regression test: `test_today_offers_a_roleplay_station_on_a_fresh_database`.
- **Admin refunds answered 500 on Postgres.** `select_for_update()` over the nullable `user` join is refused by Postgres ("FOR UPDATE cannot be applied to the nullable side of an outer join"). SQLite ignores locking, so the SQLite suite never saw it. The lock is now `of=("self",)`.
- **Test infrastructure: the Postgres suite dried the connection pool.** channels' test communicator swaps `close_old_connections` for a no-op, so every socket a test opens pinned a pooled connection until the communicator disconnected; after a dozen sockets every later test timed out. Settings skip the psycopg pool when `PYTEST_VERSION` is set. Production is unaffected: with the pool on, 14 sockets opened and closed in a row left the pool size stable (verified by direct measurement).

## Live walkthrough on the Docker stack (http://localhost:8080, real AI, Postgres, nginx)

- Login page · dark theme from the device preference, Google button hidden (`/api/users/auth-config/` returns an empty id), passkey button, skip-to-content link and `#main` present · working
- Password sign-in (demo teacher) · working
- Home, Today (3 stations incl. role-play), My courses, course page with the adaptive path, lesson, Review, Paths, Role-play studio · working
- Ask Aasan (typed) · streamed a real answer over the WebSocket, no console errors · working (tap-to-talk needs a microphone; the voice suites cover the server side)
- Live Class, Workshops list, Certificates, Plans & billing (test-mode banner), Account (passkeys, extension pairing code generated), Connect Claude · working
- School cockpit · every tab, including Workshops which is now on by default (0 seats message as designed until seats are set) · working
- Creator Lab · working (tour shows)
- Admin console · Overview, Users, Organisations, Refunds (the Postgres fix verified live), Email (SMTP configured in the console, test mail arrives in Mailpit), Providers ("Test connection" → "Replied: OK"), System check, Workshops; in English and in Tamil · working
- Workshop test run · prerequisite screen → start → Kili's first teaching turn with real AI · working
- Theme "Follow my device" · resolved to dark with the device in dark mode, and back to light when the device changes · working
- 390 px layout · covered by `mobile.e2e.ts` and `a11y.e2e.ts` (both green)
- SMTP via the admin console · settings saved, test mail and a real verification mail arrived in Mailpit from the configured sender · working

## Not built in 1.0.0, by decision

- Object storage (S3) for media: media stays on the `mediafiles` volume, backed up nightly by `infra/backup.sh`.
- Transactional email API providers: SMTP only (configured in Admin → Email).
- Continuous deployment: CI validates; deploys follow `docs/DEPLOY.md` by hand.
- Two admin corners still show English in every language: the email `TemplateEditor` and the chart table/graph toggle.

## Owner steps after deploy

See `CHANGELOG.md` → "Owner setup after deploy" (Google client id, SMTP, Deepgram or Sarvam key, Razorpay live keys, institution seat counts).
