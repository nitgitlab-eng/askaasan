# Aasan 1.3.0: server hand-off

Release 1.3.0 · Nov 2, 2026 · Nandha Infotech

This guide is for the developer who puts Aasan on a server. You build the images from the source in this package,
so you need no CI, no container registry and no access to the original machine. Following the steps below gets you
from an empty Linux server to **https://askaasan.com**.

Other documents, all in this package:
- `docs/DEPLOY.md`: the full runbook (backups, scaling, monitoring, updates).
- `docs/GO-LIVE-askaasan.md`: the domain-specific values and the launch checklist.
- `docs/FEATURES.md`: every feature, marked with its status.
- `docs/RELEASE-1.3.0-VALIDATION.md`: what was tested for this release.

---

## 1. What you are deploying

Aasan is a Tamil-first AI mentor app. These parts are covered in this guide:
- web app (React);
- API (Django + Channels);
- background jobs (Celery);
- optional live voice (LiveKit).

It runs as one Docker Compose stack:

| Service | Role | Notes |
|---|---|---|
| `db` | Postgres 16 | data volume `pgdata` |
| `redis` | Celery broker, WebSocket layer, security counters | never evicts, append-only |
| `redis-cache` | Django cache (throttles) | LRU, in memory only |
| `migrate` | Runs database migrations once per `up`, then exits | other services wait for it |
| `api` | gunicorn + uvicorn (HTTP and WebSockets) | `GET /api/health/ready/` |
| `worker` / `beat` | Celery worker and the scheduler (emails, course generation, nightly jobs) | only one `beat` is allowed |
| `mailpit` | Catches mail when no SMTP server is set | UI on `127.0.0.1:8025` |
| `web` | nginx: the React build, the `/api` + `/ws` proxy, media | bound to `127.0.0.1:8080` |
| `livekit`, `voice-agent` | Live voice calls (only with `--profile voice`) | UDP 7882, TCP 7881 |

HTTPS is handled by **Caddy** on the host, in front of `web` (`infra/Caddyfile`).

## 2. Server requirements

| Item | Requirement |
|---|---|
| OS | Ubuntu 22.04 / 24.04 LTS (any Linux with Docker works), **x86-64 (amd64) or ARM64** |
| Size | 4 vCPU / 16 GB RAM minimum (8 vCPU recommended at scale), **160 GB** NVMe disk. The API image is ~3 GB |
| Software | Docker Engine 24+ with the Compose v2 plugin (`docker compose version`), `openssl`, `unzip`, Caddy 2 |
| Region | India (data residency, latency for learners). See `docs/INFRA-RECOMMENDATION.md` |
| Open ports | 80/tcp, 443/tcp; for live voice also 7882/udp and 7881/tcp (with TURN also 3478/udp and 5349/tcp) |
| Outbound | HTTPS to the AI providers, Razorpay, the mail server, browser push services, `api.pwnedpasswords.com` |

The build downloads packages from PyPI, npm and Docker Hub, so the server needs internet access while building.

Install Docker on Ubuntu:

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER      # log out and back in
sudo apt-get install -y unzip openssl caddy   # Caddy: see https://caddyserver.com/docs/install if apt lacks it
```

## 3. Deploy step by step

```sh
# 1. Unpack (keep this path: cron and the backup scripts run from it)
sudo mkdir -p /srv && sudo chown $USER /srv
unzip Aasan-1.3.0-server-handoff.zip -d /tmp/aasan-pkg
cp -r /tmp/aasan-pkg/aasan-1.3.0-source /srv/aasan && cd /srv/aasan

# 2. Generate the settings files (infra/.env and api/.env). Random passwords and secret keys; nothing is printed.
#    This builds the API image once (5-15 minutes the first time).
bash infra/init-env.sh askaasan.com

# 3. Add the owner's keys to api/.env (section 4). At least an AI key and SENTRY_DSN (or SENTRY_OPTIONAL=1).
nano api/.env

# 4. Build and start everything (live voice included)
docker compose -f infra/docker-compose.yml --profile voice up -d --build
docker compose -f infra/docker-compose.yml ps           # all "healthy"; migrate "exited (0)"
curl -fsS http://127.0.0.1:8080/api/health/ready/       # {"ok": true, ...}

# 5. HTTPS: Caddy gets the Let's Encrypt certificate (DNS must already point at this server, section 5)
sudo cp infra/Caddyfile /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -fsS https://askaasan.com/api/health/ready/

# 6. First admin: sign up at https://askaasan.com, then
docker compose -f infra/docker-compose.yml exec api python manage.py make_admin <owner email>
```

Then sign in. Open **Admin → System check** and clear every red and amber item.

- If the API container keeps restarting, run `docker compose -f infra/docker-compose.yml logs api`. On a public
  address the API **refuses to start** with unsafe settings, and the log lists each problem. The usual causes:
  - no `SENTRY_DSN`;
  - LiveKit's dev keys;
  - `http://` in `FRONTEND_URL`;
  - a readable `api/.env` (fix with `chmod 600 api/.env`).
- Without live voice, leave out `--profile voice`. Voice then uses the browser or Deepgram.
- **Never run `seed_demo` on the live server.** It creates demo accounts.

Every `docker compose` command (including `exec`, `logs` and `infra/backup.sh`) reads `TAG` from `infra/.env`.
`init-env.sh` sets it to `v1.3.0-local`, which names the locally built images `aasan-api:v1.3.0-local` and
`aasan-web:v1.3.0-local`.

## 4. Keys and accounts the owner must supply

The keys go in `api/.env`. Keys marked *admin* can be entered later in the admin console instead (they are stored
encrypted).

| What | Setting | Needed? | Where it comes from |
|---|---|---|---|
| AI model | `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` / `GEMINI_API_KEY`) | **Required** for real answers. *admin*: AI & Voice providers | console.anthropic.com |
| AI fallback | `LLM_FALLBACK`, `LLM_MONTHLY_BUDGET` | Recommended | a second provider; budget in USD for 50/80/95% alerts |
| Error monitoring | `SENTRY_DSN` | **Required** on a public site (or `SENTRY_OPTIONAL=1`) | sentry.io or self-hosted GlitchTip |
| Admin email | `DJANGO_ADMINS` | Recommended | owner's email |
| Mail (SMTP) | `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` in `infra/.env` | **Required** (verification, password reset, guardian consent). *admin*: Email | Zoho Mail / SES / any SMTP; set SPF, DKIM, DMARC |
| Payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Required to sell plans. *admin*: Payments | Razorpay dashboard; webhook in DEPLOY.md §5 |
| Tamil voice + live voice | `SARVAM_API_KEY` | Required for live voice and Tamil server voices. *admin* | sarvam.ai |
| Interrupt-by-voice | `DEEPGRAM_API_KEY` | Optional | deepgram.com |
| Google sign-in | `GOOGLE_CLIENT_ID` | Optional (button hidden until set) | Google Cloud console, origin `https://askaasan.com` |
| Calendar sync | `GOOGLE_CALENDAR_*`, `MICROSOFT_CALENDAR_*` | Optional | redirect URIs in GO-LIVE §4 |
| Metrics | `METRICS_TOKEN` | Optional (monitoring overlay) | `openssl rand -hex 32` |
| Backups | `BACKUP_AGE_RECIPIENT`, `BACKUP_COPY_CMD` in `infra/.env` | **Required** | an `age` key pair (the private key stays off the server); an rclone/S3/rsync target |

Generated by `init-env.sh`, so you don't touch these:
- `POSTGRES_PASSWORD`, `REDIS_PASSWORD`;
- `DJANGO_SECRET_KEY`, `AASAN_SECRETS_KEY`;
- the web-push key pair;
- `LIVEKIT_API_SECRET`.

**Keep a copy of `api/.env` and `infra/.env` in a password manager.** If you lose `AASAN_SECRETS_KEY`, every key
saved in the admin console is lost.

Every setting is documented in `api/.env.example` and `infra/.env.example`.

## 5. DNS and outside consoles

| Record | Name | Value |
|---|---|---|
| A (+ AAAA) | `askaasan.com` | server IP |
| A / CNAME | `www.askaasan.com` | same server (Caddy redirects it to `askaasan.com`) |
| TXT | SPF, DKIM, `_dmarc` | from the mail provider |

`https://askaasan.com` must be the only address users see. Passkeys, cookies and OAuth redirects are tied to it.

Console settings (Google, Microsoft, Razorpay webhook, uptime monitor): see `docs/GO-LIVE-askaasan.md` §4.

## 6. After deploy: checklist

- [ ] `docker compose -f infra/docker-compose.yml ps`: every service healthy.
- [ ] `https://askaasan.com/api/health/ready/` returns 200. `http://` and `www` redirect to `https://askaasan.com`.
- [ ] Sign up, get the verification email, sign in, add a passkey.
- [ ] Admin → System check: no red items.
- [ ] Ask Aasan answers (needs the AI key). A course can be created and a lesson opened.
- [ ] `docker compose -f infra/docker-compose.yml exec api python manage.py check_guardrails` passes (safety
      red-team set; needs the AI key).
- [ ] An under-18 sign-up sends the guardian a consent email. AI features stay locked until the guardian agrees.
- [ ] A Razorpay test payment completes, and the webhook shows as delivered in the Razorpay dashboard.
- [ ] Live voice: a call connects on Wi-Fi and on mobile data (needs the Sarvam key and the UDP port).
- [ ] Backups: `bash infra/backup.sh` succeeds; then `bash infra/restore.sh --drill` (DEPLOY.md §7).
- [ ] Cron: `15 2 * * * cd /srv/aasan && bash infra/backup.sh >> /var/log/aasan-backup.log 2>&1`
- [ ] An uptime monitor watches `https://askaasan.com/api/health/ready/`.
- [ ] Walk through the feature checks in `docs/GO-LIVE-askaasan.md` §6.

## 7. Day-2 operations

| Task | How |
|---|---|
| Logs | `docker compose -f infra/docker-compose.yml logs -f api worker` |
| Update to a new release | Unpack the new source over a copy and keep `api/.env` and `infra/.env`. Set `TAG=v<new>-local`, run `up -d --build`. Migrations run on their own. See DEPLOY.md §10 |
| Roll back | Set `TAG` back to the previous value (its images are still on the server), then `up -d --no-build` |
| Restart one service | `docker compose -f infra/docker-compose.yml restart api` |
| Make a staff user | `... exec api python manage.py make_admin <email> --role support` (roles: superadmin, support, finance, content) |
| Monitoring stack | `-f infra/docker-compose.monitoring.yml` (Prometheus, Grafana, Alertmanager, Loki). See DEPLOY.md "Monitoring" |
| Point-in-time recovery | Optional WAL-G overlay `infra/docker-compose.pitr.yml`. See DEPLOY.md §7.3 |
| Scaling | `WEB_CONCURRENCY` (use 5 on 4 vCPU), DB pool and Postgres memory knobs in `infra/.env`. See DEPLOY.md §8–9 |
| Disk cleanup | `docker image prune` once older releases are no longer needed for rollback |

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `set TAG in infra/.env ...` | `infra/.env` is missing or has no `TAG`. Run `bash infra/init-env.sh <domain>` |
| API restarts with a list of "unsafe settings" | Fix each listed item in `api/.env` / `infra/.env` (section 3) |
| Build fails at `uv sync` (download error) | Temporary network or PyPI problem: rerun the build. On Docker Desktop, restart Docker |
| Passkeys fail | The site must be opened at exactly `WEBAUTHN_ORIGIN`, and `WEBAUTHN_RP_ID` must be its bare host name |
| Emails not arriving | No SMTP set means mail goes to mailpit (`ssh -L 8025:127.0.0.1:8025` then http://localhost:8025) |
| Live voice connects but no audio | UDP 7882 is blocked: open it, or turn on TURN (`infra/docker-compose.turn.yml`) |
| `502` from Caddy | `web` is not healthy yet. Check `docker compose ... ps` and `logs web api` |

## 9. What is in this package

| Path | What |
|---|---|
| `api/` | Django API, Celery tasks, LLM layer, tests (`uv run pytest`) |
| `web/` | React app (`pnpm build`) |
| `extension/` | Browser extension (Chrome/Edge store upload; defaults to https://askaasan.com) |
| `infra/` | Compose files, Dockerfiles, nginx, Caddyfile, `init-env.sh`, `backup.sh`, `restore.sh`, monitoring |
| `docs/` | This guide, DEPLOY, GO-LIVE, FEATURES, validation records, specs |
| `.github/workflows/` | CI and release-image workflows. Optional: use them once the code is on GitHub |

The package contains **no secrets**: no `.env` files, no keys and no data. Production data starts empty.
