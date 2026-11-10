# Aasan web

The Aasan web app: React 19 + Vite + TypeScript, Tailwind CSS 4, TanStack Query, Zustand, i18next.

## Run

```bash
pnpm install
pnpm dev          # http://localhost:5173 (use localhost, not 127.0.0.1, so passkeys work)
```

The dev server proxies `/api` and `/ws` to the Django API on `127.0.0.1:8000` (see `vite.config.ts`), so start the API
first (see the repository README). In Docker, nginx serves `pnpm build` output and proxies to the API instead
(`infra/web.Dockerfile`, `infra/nginx/default.conf`).

## Scripts

| Command | What |
| --- | --- |
| `pnpm dev` | Vite dev server with hot reload |
| `pnpm build` | Type-check (`tsc -b`) and build to `dist/` |
| `pnpm test` | Unit tests (vitest + Testing Library, jsdom) |
| `pnpm lint` | oxlint |
| `pnpm preview` | Serve the production build locally |

## Layout

| Path | What |
| --- | --- |
| `src/pages/` | Routed screens |
| `src/components/` | Shared UI |
| `src/activities/` | Lesson activity types (quiz, code, map, video, ...) |
| `src/mascot/` | The Kili mascot engine and store (`mascot.react(...)`, `mascot.say(...)`) |
| `src/i18n/` | Interface strings. `en.ts` is the source; `locales/*.json` are the other languages (`languages.ts` marks machine translations still awaiting review) |
| `src/lib/`, `src/stores/` | API client, helpers and Zustand stores |
| `scripts/export-i18n.mjs` | Writes `src/i18n/locales/en.json` for `manage.py translate_ui` |

Tests live next to the code as `*.test.ts(x)`. Dependency versions are resolved by `pnpm-lock.yaml`; install with
`pnpm install --frozen-lockfile` in CI and Docker.
