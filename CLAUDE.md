# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Aasan (ஆசான்): a Tamil-first AI mentor app with Kili, a parrot mascot. Monorepo: `api/` (Django 5 + DRF + Channels,
Python 3.12, uv), `web/` (React 19 + Vite + TS, Tailwind 4, TanStack Query, Zustand, i18next, pnpm), `extension/`
(MV3 browser extension, plain JS), `infra/` (docker-compose: Postgres, Redis, daphne API, Celery worker + beat, nginx).
README.md has the full setup and the AI Workshops security model.

## Commands

API (run from `api/`):
- First setup: `uv sync && uv run python manage.py setup_env && echo "LLM_FORCE_PROVIDER=fake" >> .env && uv run python manage.py migrate && uv run python manage.py seed_demo`
- Run: `uv run python manage.py runserver 127.0.0.1:8000`
- Tests: `uv run pytest` — single file/test: `uv run pytest tests/test_mentor_ws.py -k name`
- Lint/format: `uv run ruff check .` and `uv run ruff format --check .` (line length 110)
- After model changes: `uv run python manage.py makemigrations --check --dry-run` must be clean in CI
- Other commands: `check_llm`, `make_admin <email>`, `make_creator <email>`, `seed_workshops`, `translate_ui`, `clean_media --dry-run`

Web (run from `web/`):
- `pnpm dev` → open http://localhost:5173 (NOT 127.0.0.1 — passkeys require the `localhost` RP ID). Proxies `/api` and `/ws` to 127.0.0.1:8000.
- `pnpm test` (vitest; single: `pnpm vitest run src/lib/api.test.ts`), `pnpm lint` (oxlint), `pnpm build` (`tsc -b` + vite — this is the type check)
- E2E: `pnpm e2e` (Playwright, specs are `e2e/specs/*.e2e.ts`; needs API running with `LLM_FORCE_PROVIDER=fake` and the dev server)

Extension (from repo root): `node --test extension/test/*.test.js`

Docker (prod-like): `docker compose -f infra/docker-compose.yml up --build` → http://localhost:8080 (needs `infra/.env` from `.env.example`,
with `TAG=dev`; compose refuses to run without TAG). Prod/staging pull CI-built GHCR images by TAG (`release-images.yml`), staging
adds `-f infra/docker-compose.staging.yml`; see docs/DEPLOY.md §10–11.

CI also runs the API suite against Postgres (SQLite ignores `select_for_update`), so locking code must be valid there.
Lockfiles (`uv.lock`, `pnpm-lock.yaml`) are authoritative; CI installs frozen.

## Architecture

- **Routing**: HTTP routes are mounted in `api/config/urls.py` (`/api/<app>/` → `apps/<app>/urls.py`). WebSockets are
  in `api/config/asgi.py`: mentor (`apps/mentor/routing.py`), `ws/roleplay/`, `ws/live/`, `ws/workshop/<session_id>/`,
  `ws/workshop-runs/<run_id>/monitor/`. Each socket gets its own thread pool (`config/asgi_threads.py`).
- **LLM layer** (`api/llm/`): call `llm.router.resolve(task)` to get a metered provider + model. Resolution order:
  `LLM_FORCE_PROVIDER` → admin-console config in DB (`apps/providers`, task→capability map in `apps/providers/catalog.py`)
  → `.env`. A new provider is built per call (async clients are event-loop bound); close it with `aclose`. Providers:
  anthropic, openai, gemini, fake. Prompts live in `api/llm/prompts/<feature>.py`.
- **Untrusted text**: anything learner-, document- or external-sourced must be wrapped with `llm.fence.fence(tag, text)`
  before it goes into a prompt. Outbound fetches to user-supplied URLs go through `apps.learning.safe_fetch`.
- **Background jobs**: Celery (`config/celery.py`); `apps/learning/jobs.py` dispatches, and `LEARNING_JOBS_INLINE=True`
  runs them synchronously (tests set it).
- **Tests**: `api/tests/conftest.py` autouse fixture forces the fake LLM, inline jobs, clears the cache (throttles) and
  strips Razorpay env keys. Use the `auth` fixture for an authenticated `APIClient`; `keys`/`gateway` fake Razorpay.
- **Throttles/lockouts** live in the Django cache — Redis when `REDIS_URL`/`CACHE_REDIS_URL` is set, otherwise per-process.
- **Web**: routed screens in `src/pages/`, API clients + hooks in `src/lib/` (sockets: `useMentorSocket.ts`,
  `live/useLiveSocket.ts`), stores in `src/stores/`, lesson activity types in `src/activities/`, voice in `src/voice/`.
  Tests sit next to code as `*.test.ts(x)`. Path alias `@/` → `src/`.
- **Mascot**: drive Kili via `mascot.react(state)` / `mascot.say(text, {actions})` from `@/mascot/store`; the server
  can send `{"type":"mascot","state":...}` over the WebSocket.
- **i18n**: `web/src/i18n/en.ts` is the source of truth. en and ta (`ta.ts`) are hand-written; other locales
  (`locales/*.json`) are machine-translated via `scripts/export-i18n.mjs` + `manage.py translate_ui`. Add new UI
  strings to `en.ts` and `ta.ts` rather than hardcoding.
- **AI Workshops** (`apps/workshops/`, `web/src/pages/workshops/`): server owns all state; answer keys, rubrics and hidden
  tests never reach the client. MCP server at `POST /api/workshops/mcp/` (per-session `awt_…` tokens), external MCP via
  `mcp_client.py`. Load check: `uv run python scripts/workshop_load.py`.
- **Adaptive learning** (`apps/adaptive/`): goal interview → concept graph → per-learner `LearnerPath`. The planner
  (`planner.py`) is pure; `services.py` is the glue (mastery from first attempts, re-plan on lesson complete /
  checkpoint / fast-track / practice, completion gating, certificate check). Only learners with a path are affected.
- **Admin roles**: `apps/accounts/staff.py` maps each `/api/admin/<section>/` to roles; admin views use `AdminSection`
  (never `IsAdminUser`). New admin endpoints must get an entry there. `AdminAudit` middleware logs every admin
  mutation. List endpoints page and export via `apps/accounts/admin_paging.paged` (`?page=`, `?export=csv` — not
  `?format=`, which DRF reserves).
- Every config setting is documented in `api/.env.example`; deploy notes in `docs/DEPLOY.md`, specs in `docs/specs/`.
