# Release 1.3.0 validation record (2026-11-02)

1.3.0 is the askaasan.com go-live release. It brings together:
- live voice (LiveKit + Sarvam);
- guardrails and live web search in every conversation;
- the course map;
- the technical gap-review hardening: guardian consent, retention, durable lockouts, staff second factor, LLM
  failover, metrics and monitoring, encrypted backups with a restore drill, and CI security gates.

It also adds a server hand-off: `docs/SERVER-HANDOFF.md` and `infra/init-env.sh`. A server can build and run Aasan
from the source alone.

## Automated checks (final tree)

| Check | Result |
|---|---|
| Backend pytest, SQLite | 2050 passed, 6 skipped |
| Backend pytest, Postgres 16 | 2056 passed |
| ruff check + format, `makemigrations --check` | clean |
| Web vitest | 641 passed (112 files) |
| Web lint (oxlint), `tsc -b` + vite build | clean |
| Extension node:test | 16 passed |

The Postgres teardown printed one warning: "test database is being accessed by other users". It comes after the
last test and is harmless.

## Clean-room deploy (exactly as SERVER-HANDOFF.md says)

The source was exported with `git archive` into an empty folder. That copy has no `.env`, no images and no
history. Nothing outside the folder was used.

1. `bash infra/init-env.sh localhost`
   - It wrote `infra/.env`: random Postgres/Redis passwords and `TAG=v1.3.0-local`.
   - It built `aasan-api:v1.3.0-local`, then generated `api/.env` inside the image: secret keys and the web-push
     pair, 93 settings.
   - No secret was printed. Both files are mode 600.
2. `docker compose -f infra/docker-compose.yml --profile voice up -d --build`
   - Ran with the `docker-compose.loadtest.yml` overlay, which sets `LLM_FORCE_PROVIDER=fake` because no AI key
     exists locally.
   - Result: all 10 services healthy and `migrate` exited 0 on a fresh database. The 10 services are db, redis,
     redis-cache, api, worker, beat, mailpit, web, livekit and voice-agent.
3. `GET /api/health/ready/` returned `{"ok": true, "checks": {"db": "ok", "cache": "ok", "channels": "ok"}}`.
   `GET /` returned 200.
4. `seed_demo` refused: "for local development only". That is the guard keeping demo accounts off a production
   build. `seed_workshops` seeded 4 workshops.

## Live checks on that stack (http://localhost:8080)

| Check | Result |
|---|---|
| Sign up (API) → sign in → `/me` | working |
| `make_admin` | "admin console access granted" |
| Under-18 sign-up | the guardian receives "Please confirm: your child wants to use Aasan" (Mailpit), and the learner gets the verification email |
| Browser: sign in → onboarding ("Pick options myself", 8 steps) → "Build my first course" | course built; the course page opens on the new **Map** view with Map / Path switch, the before/after test and Save for offline |
| Ask Aasan (WebSocket) | streamed reply; shows the demo-mode notice because no AI key is set |
| Admin → System check | **0 must fix**, 13 to review (expected without keys: AI providers, Razorpay, SMTP, legal details, Sentry, HTTPS), 9 OK (Postgres, Celery + beat, media, debug off, custom secret key, encryption key, no demo accounts, 1 superadmin) |
| `infra/backup.sh` (age-encrypted, off-site copy command) | `db-….dump.age`, `media-….tgz.age` and a sha256 manifest, copied off-site |
| `infra/restore.sh --drill` from the off-site copy | "restored, checked and dropped" (2 users, 141 migrations) |

## Universal build

| Platform | Result |
|---|---|
| linux/arm64 (this Mac) | both images built and the stack ran (above) |
| linux/amd64 (`docker buildx --platform linux/amd64`) | `infra/api.Dockerfile` and `infra/web.Dockerfile` both built (uv sync, voice model download, collectstatic, vite build) |

## Not checked here (needs the owner's accounts or a real server)

- Real AI answers, the chat interview in onboarding, and `check_guardrails`. These need an Anthropic, OpenAI or
  Gemini key. With the fake provider, the onboarding chat repeats its first question; use "Pick options myself".
- Razorpay live/test payment and webhook, real SMTP delivery, Sentry events.
- Live voice audio: the LiveKit and voice-agent containers are healthy, but a call needs the Sarvam key.
- HTTPS through Caddy and Let's Encrypt: needs the domain pointing at the server.
- WAL-G point-in-time recovery against a real S3 bucket. The GitHub workflows have never run on GitHub's runners
  (no remote yet).
