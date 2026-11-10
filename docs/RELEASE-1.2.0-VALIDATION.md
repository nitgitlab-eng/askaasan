# Release 1.2.0 validation record (2026-10-25)

1.2.0 makes reminders Duolingo-like: the companion's voice and personality, learned study time, step-up after a missed day, and backing off when reminders are ignored.

## Automated checks (final tree)

| Check | Result |
|---|---|
| Backend pytest, SQLite | 1868 passed, 6 skipped |
| Backend pytest, Postgres 16 | 1874 passed |
| ruff check + format, `makemigrations --check` | clean |
| Web vitest | 592 passed (105 files) |
| Web lint, `tsc -b` + build, e2e type-check | clean |
| Extension node:test | 15 passed |
| Playwright (23 specs) | 49 passed, no retries |
| 7 machine locales | the 7 new UI strings translated, placeholders intact |

New test files: `test_voice.py` (every moment × language × personality, matching ids and placeholders, length limits, rotation), `test_besttime.py`, `test_stepup.py`, `test_push_backoff.py`; `test_push.py`, `test_winback.py` and `PushCard.test.tsx` updated.

## Live check on the Docker stack (http://localhost:8080, Postgres)

Migration `accounts.0012_reminders` applied to the existing data. Scenarios ran inside the API container with throwaway test learners (deleted afterwards); pushes were captured in the container, never sent to a push service.

- **Learned time**: first lessons at 07:40 on 6 days → learned 07:40, nudge at 08:00 (07:10 clamped to the 08:00 quiet-hours edge); `GET /api/users/push/` shows `learned_time: "07:40"` · working
- **Companion voice**: English, Funny buddy, Yaanai: "Arun! 4 days. Don't ghost it now" / "Your streak sent 47 worried messages…"; Tamil, Strict teacher, Mayil: "🦚 இன்று இன்னும் பாடம் இல்லை" in both the push and the bell · working
- **Variety**: the next streak-risk message rotated from variant 1 to variant 2 · working
- **Step-up**: with no freeze, the day the streak broke: "🦜 Your 5-day streak can come back" (repair link); a rerun the same day sent nothing; the next day: "Karthik, last chance for your 5 days · Only 48 hours left to repair it". With the default one freeze, the first missed day is covered (no "broke" message) and the step-up starts the day after · working as designed
- **Back-off**: 8 ignored reminders → paused; study reminders held, win-back and teacher messages still allowed; the "I've paused your reminders" notice sent once (a second run sent nothing); the open ping (`POST /api/users/push/opened/`) answered 204 for a real and a junk id, and the real one brought reminders back to normal · working

## Not checked live

- Accepting the browser's notification permission and receiving a real push on a device (needs the owner to click "Allow"); delivery is covered by `test_push.py`.
- A Playwright spec for the back-off banner on Account (covered by `PushCard.test.tsx`).

## Owner notes

- About 96 Tamil push title/body pairs in `api/apps/accounts/voice.py` and the new Tamil UI strings should be read by a native speaker before launch. Funny buddy and Anna/Akka lines are deliberately colloquial.
- Restart Celery beat after deploy (`stepup-checks`, `reminder-nightly`; `evening-checks` now every 15 minutes).
