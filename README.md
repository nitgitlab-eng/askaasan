# Aasan · ஆசான்

A playful, Tamil-first AI mentor for students and aspiring learners, with **Kili (கிளி)**, a live parrot companion that reacts as you learn.

| Folder | What |
|---|---|
| `api/` | Django 5 + DRF + Channels. Auth (email, Google, passkeys), preferences, streaming mentor over WebSocket, multi-provider LLM layer (`api/llm/`), Celery jobs |
| `web/` | React + Vite + TypeScript. Tamil-first i18n (9 languages), themes, Kili mascot engine (`web/src/mascot/`), Personalize studio |
| `extension/` | Aasan Companion, a Manifest V3 browser extension for browser tasks (see `extension/README.md`) |
| `infra/` | docker-compose for Postgres, Redis, API (daphne), Celery worker + beat, nginx serving the web build |

**Quick links:** [Changelog](CHANGELOG.md) · [Server hand-off](docs/SERVER-HANDOFF.md) · [Deploy guide](docs/DEPLOY.md) · [Feature list](docs/FEATURES.md) · [1.0.0 validation record](docs/RELEASE-1.0.0-VALIDATION.md) · [1.1.0 validation record](docs/RELEASE-1.1.0-VALIDATION.md) · [1.2.0 validation record](docs/RELEASE-1.2.0-VALIDATION.md) · [1.3.0 validation record](docs/RELEASE-1.3.0-VALIDATION.md) · [Settings reference](api/.env.example) · [Extension](extension/README.md) · [Licence](LICENSE)

## Run locally (no Docker, no API key needed)

```bash
# API: SQLite + in-memory channels; LLM_FORCE_PROVIDER=fake gives a canned Tamil tutor
cd api
uv sync
uv run python manage.py setup_env        # creates .env from .env.example with a generated DJANGO_SECRET_KEY + AASAN_SECRETS_KEY
echo "LLM_FORCE_PROVIDER=fake" >> .env
uv run python manage.py migrate
uv run python manage.py seed_demo        # demo accounts (DEBUG only; add --full for a showcase course and school)
uv run python manage.py runserver 127.0.0.1:8000

# Web (new terminal)
cd web && pnpm install && pnpm dev       # open http://localhost:5173
```

Open the app at **http://localhost:5173**, not 127.0.0.1: passkeys only work on the host that matches
`WEBAUTHN_RP_ID` (`localhost` by default), and `FRONTEND_URL` / CORS use `localhost` too. The Vite dev server proxies
`/api` and `/ws` to the API on 127.0.0.1:8000.

To use real models, remove `LLM_FORCE_PROVIDER` and set `ANTHROPIC_API_KEY` (default routes: tutor → `claude-sonnet-5-5`,
grading → `claude-haiku-5-5`). You can route any task to another provider, e.g. `LLM_ROUTE_TUTOR=gemini:gemini-2.5-flash`
or `openai:<model>`. `uv run python manage.py check_llm` checks the configured providers. Every setting is listed, with
comments, in `api/.env.example`.

Google sign-in appears on the login and sign-up pages once `GOOGLE_CLIENT_ID` is set (an OAuth web client whose
authorised JavaScript origin is the site URL — see docs/DEPLOY.md); without it the button is simply not shown.

Useful commands: `make_admin <email>` (admin console access), `make_creator <email>` (Creator Lab), `clean_media --dry-run`.

## Run with Docker (production-like)

```bash
cd api && uv run python manage.py setup_env && cd ..       # api/.env with generated secrets
cp infra/.env.example infra/.env                           # then set POSTGRES_PASSWORD and REDIS_PASSWORD (openssl rand -hex 24), and TAG=dev
docker compose -f infra/docker-compose.yml up --build      # open http://localhost:8080
```

`TAG` is required by every compose command. `TAG=dev` builds the images locally; servers set a release tag and
`AASAN_IMAGE_PREFIX=ghcr.io/<owner>/aasan` and pull the images CI published, never building on the host (see
"Deploy from registry" and "Staging and release runbook" in [docs/DEPLOY.md](docs/DEPLOY.md)).

A one-shot `migrate` service applies migrations before the API, worker and beat start. Only nginx (`web`, port 8080)
is published; Postgres, Redis and the API stay on the internal compose network. Compose forces `DJANGO_DEBUG=false` and
sets `FRONTEND_URL` / `WEBAUTHN_ORIGIN` to `http://localhost:8080`; for a real domain set `FRONTEND_URL`,
`WEBAUTHN_ORIGIN`, `WEBAUTHN_RP_ID`, `DJANGO_ALLOWED_HOSTS` and `DJANGO_SECURE_SSL_REDIRECT=true` in `infra/.env`, and put
HTTPS in front of `web`. Throttles, login lockouts, mail caps and the extension pairing limit live in the Django
cache, which is Redis whenever `REDIS_URL` / `CACHE_REDIS_URL` is set (compose does this), so they hold across every
API and worker process; without Redis each process counts on its own. Lesson images and lecture media are served by nginx from the shared media volume.
`infra/backup.sh` dumps the database and media nightly, encrypted with age and copied off the server; `infra/restore.sh --drill` checks a backup (docs/DEPLOY.md §7).

## Tests

```bash
cd api && uv run pytest                        # API (runs offline with the fake LLM provider)
cd web && pnpm test                            # web unit tests (vitest)
node --test extension/test/*.test.js           # extension, from the repo root (no dependencies)
```

CI (`.github/workflows/ci.yml`) also runs `ruff check`, `ruff format --check`, `makemigrations --check`,
`manage.py check --deploy`, `pnpm lint` and `pnpm build` (which type-checks with `tsc -b`).

Dependencies: version ranges in `api/pyproject.toml` and `web/package.json` are minimums; `api/uv.lock` and
`web/pnpm-lock.yaml` are authoritative (CI and Docker install with `--frozen` / `--frozen-lockfile`). Upgrade on purpose
and run the tests.

## AI Workshops

Learner-paced workshops run by Kili, with no human trainer (`api/apps/workshops/`, `web/src/pages/workshops/`). Each
learner works through a template's agenda (teach, check, DIY, `build` hand-ins graded like lesson activities, the
agent builder, and a final assessment) at their own speed. Time is only a guide: nothing is ever cut off or submitted
for them. Passing the final at the template's pass mark issues an Aasan certificate.

**Scheduling.**
- Public runs: Admin console → Workshops. Create a run from a template, set the start time, capacity and price
  (0 = free), publish, then announce it. Announcements go out in batches; each user is told once.
- Paid seats use the Razorpay keys under Payments & plans. A seat is granted only after Razorpay confirms the capture
  (verify callback, webhook, or the 10-minute reconciliation task for webhooks that can't reach local or dev hosts).
- Learners get reminders 24 h and 15 min before the start. Status moves scheduled → live → ended on its own.
- Institution runs: every org's `workshops` feature is on by default; only the platform admin can switch it off
  (an explicit off also keeps that org's learners out of public workshops), and only the platform admin sets the
  monthly `workshop_seats` quota, which starts at 0 so nothing can be scheduled until it is set. Org owners and
  admins then schedule free runs for chosen classes and cohorts from the org dashboard. Teachers watch a live monitor (tiles, raised hands, nudges) and download reports (PDF, PPTX, CSV) for
  their own classes only.
- Staff can try any template privately with a test run.

**MCP tools URL.** The agent builder's built-in tools (calculator, workshop notes search, dates, units, word count)
are also served as a real MCP server: Streamable HTTP at `POST /api/workshops/mcp/` (JSON-RPC 2.0). It accepts only a
per-session `awt_…` token, which lasts at most 24 h, is bound to one session and user, and dies when the session is
submitted. Learners can also connect their own remote MCP servers over https.

**Security model.**
- The server owns all state. Final MCQ keys, practical rubrics, hidden agent tests and `build` rubrics or model
  answers never leave the server.
- Everything a learner, an error log, a screenshot or an external MCP server sends is fenced and defanged as
  untrusted data before it reaches a model. No agent tool runs without the learner's approval.
- External MCP calls go through `safe_fetch`: https only, public IPs re-resolved and pinned per request, no
  redirects, size and time caps, and only the learner's own auth header is forwarded.
- Learner MCP tokens are encrypted at rest and wiped on submit (and after 7 days at the latest).
- Help screenshots are never stored; only the AI's 200-character summary is kept.
- Attention signals are collected only when proctoring is on, and never during hands-on stages. There is no camera.
- Transcripts and events are deleted after 90 days.
- Limits: a per-session AI budget, help requests per hour, agent test runs, external calls per minute, 5 graded
  hand-ins per build stage, and a throttled monitor fan-out.

**Settings** (`api/.env.example` lists each with its default): `WORKSHOP_SESSION_AI_UNITS`, `WORKSHOP_HELP_PER_HOUR`,
`WORKSHOP_CAP_MULTIPLIER`, `WORKSHOP_AGENT_RUNS`, `WORKSHOP_EXTERNAL_MCP` and `WORKSHOP_EXTERNAL_PER_MIN`. Celery beat
runs the reminders, run status, token cleanup, 90-day retention and payment reconciliation tasks.

Load check: `uv run python scripts/workshop_load.py` (from `api/`) simulates about 100 learner sockets on one org run
with the fake provider, in-process, and prints monitor tile latency.

## Adaptive learning

A learner can start from just a topic. Kili suggests three real-life ways to use it plus a foundations track, or checks
the learner's own use case (accept, split into smaller first steps, or decline), asks what they already know and how
much time they have, and builds the course toward that goal (`api/apps/adaptive/`, `web/src/components/adaptive/`).

- Every course has a concept graph (which lessons teach which concepts, and prerequisites). New outlines get one from
  AI; older courses get one concept per lesson, without AI.
- Each learner gets their own path over the unchanged syllabus: lessons in prerequisite order, a quick skip-check
  (fast-track) where they already know the material, and a practice step where a concept is still shaky. The course
  pre-test is the diagnostic. Mastery is Bayesian Knowledge Tracing on first attempts only.
- On a path, a lesson below the pass mark can't be finished until its practice step is done. Adaptive learners also
  need every critical concept mastered for a certificate.
- The planner is pure (`apps/adaptive/planner.py`); its thresholds are tested against the real BKT constants.

## Admin console roles

Staff have roles: **superadmin** (everything, including staff, providers, email and site settings), **support** (users,
organisations, reports, help), **finance** (payments, plans, codes, invoices, refunds) and **content** (catalog,
workshops, certificates and their design). Access is decided per `/api/admin/<section>/` in
`api/apps/accounts/staff.py`; an admin path missing from that table is superadmin-only. Staff accounts from before
roles existed are superadmins. Set roles in the console (Staff & audit log) or with
`manage.py make_admin <email> --role finance`.

Every change made through the console is written to an audit log (who, what, target, IP; secret values masked).
The console also covers users (search, deactivate, sign out everywhere), organisations (seats, features, suspension),
certificates (revoke, fix a name, design templates with a PDF preview; organisations design their own), refunds
through Razorpay, and CSV export of every list (`?export=csv`).

## Mascot API (any feature can drive Kili)

```ts
import { mascot } from "@/mascot/store";
mascot.react("cheer");                       // cheer | hmm | thinking | talking | sleepy | fire | celebrate | wave | confused
mascot.say("சூப்பர்! 🎉", { actions: [{ label: "Next", onClick }] });
```

The server can drive it too: the WebSocket sends `{"type":"mascot","state":"thinking"}` events.
