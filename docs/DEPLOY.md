# Aasan go-live runbook

This runbook covers the Docker stack in `infra/` on a single Linux host (reference: 8 cores, 16 GB RAM). Commands run
from the repo root unless noted.

For **askaasan.com**, [GO-LIVE-askaasan.md](GO-LIVE-askaasan.md) fills in every `<domain>` value below, and `infra/Caddyfile`
is ready to use. Building on the server from the source package (no CI or registry)? Follow
[SERVER-HANDOFF.md](SERVER-HANDOFF.md): `bash infra/init-env.sh <domain>` writes `infra/.env` and `api/.env`, then `up -d --build`.

## 1. What runs

| Service | What it does | Health |
|---|---|---|
| `db` | Postgres 16 (`max_connections` 300, memory tuned via `PG_*`) | `pg_isready` |
| `redis` | Celery broker (DB 0) and the Channels layer (DB 2). `noeviction` and append-only, so queued tasks are never dropped | `redis-cli ping` |
| `redis-cache` | Django cache (DB 1): throttles, login lockouts, mail caps. `allkeys-lru`, nothing on disk | `redis-cli ping` |
| `migrate` | Runs `migrate` once per `up`, then exits. The other app services wait for it | — |
| `api` | gunicorn with uvicorn workers (multi-process ASGI: HTTP and WebSockets) | `GET /api/health/ready/` |
| `worker` | Celery worker (emails, course generation, lecture processing) | `celery inspect ping` |
| `beat` | Celery beat (periodic jobs). Its schedule file is kept on the `celerybeat` volume | schedule file rewritten in the last 15 min |
| `mailpit` | Local inbox for every email the app sends (UI on `127.0.0.1:8025`) | `mailpit readyz` |
| `web` | nginx: the React build, `/api` and `/ws` proxy, lesson media from the volume | `GET /api/health/ready/` through nginx |

There are two probes:
- `/api/health/` (liveness) does no I/O.
- `/api/health/ready/` (readiness) checks the database, the cache and the channel layer, with a 2 s timeout each
  (`HEALTH_TIMEOUT`). It returns `200 {"ok": true, "checks": {...}}`, or `503` naming which check failed; the reason
  goes to the log. Both probes answer before host validation and the HTTPS redirect, so load balancers can call them
  on any host name. Point an external uptime monitor at `https://<domain>/api/health/ready/`.

## 2. First deploy

```sh
# 1. App secrets (DJANGO_SECRET_KEY, AASAN_SECRETS_KEY) in api/.env
cd api && uv run python manage.py setup_env && cd ..
# 2. Compose secrets and public address in infra/.env
cp infra/.env.example infra/.env
#    then fill in POSTGRES_PASSWORD and REDIS_PASSWORD (openssl rand -hex 24), and the values in section 3,
#    and the images to run: TAG=<release tag, e.g. v1.3.0> and AASAN_IMAGE_PREFIX=ghcr.io/<owner, lowercase>/aasan
# 3. Pull the released images (built by CI, section 10) and start. Nothing is built on the server.
docker login ghcr.io -u <github user>                  # once per host; a token with read:packages (private images)
docker compose -f infra/docker-compose.yml pull
docker compose -f infra/docker-compose.yml up -d --no-build
docker compose -f infra/docker-compose.yml ps          # every service "healthy" (migrate "exited (0)")
curl -fsS http://localhost:8080/api/health/ready/
# 4. Create the first staff account (sign up in the app first), then give it the superadmin role
docker compose -f infra/docker-compose.yml exec api python manage.py make_admin you@yourdomain.in
#    other staff get the narrowest role: --role support | finance | content (repeatable)
```

Then open **Admin → System check** and clear every red and amber item before announcing. It flags missing keys,
email, legal details, HTTPS/HSTS, error monitoring, and any leftover demo, test or validation accounts.

Every compose command (including `ps`, `exec` and `infra/backup.sh`) needs `TAG`, so keep it in `infra/.env`; without
it compose stops with "set TAG in infra/.env ...".

To run locally exactly like production, build the images on your machine instead of pulling them: set `TAG=dev` in
`infra/.env` (leave `AASAN_IMAGE_PREFIX` empty), run `docker compose -f infra/docker-compose.yml up --build -d` and
open http://localhost:8080. Mail goes to http://localhost:8025.

For a load test, run the fake AI with real-model latency and never call a paid model:

```sh
docker compose -f infra/docker-compose.yml -f infra/docker-compose.loadtest.yml up --build -d   # TAG=dev in infra/.env
# LLM_FAKE_DELAY_MS (default 800) and LLM_FAKE_TOKEN_MS (default 30) can be set in the shell or in infra/.env
```

## 3. Environment variables

The app reads secrets and keys from `api/.env`. `infra/.env` holds the compose settings, and compose overrides
`api/.env` for the keys it sets. An empty value means the default.

**Required** (infra/.env): `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `TAG` (plus `AASAN_IMAGE_PREFIX` when the images
come from the registry). (api/.env): `DJANGO_SECRET_KEY`, `AASAN_SECRETS_KEY`.

**Voice (optional):** without a key, learners hear their browser's built-in voice. For server voices, set a key in
Admin → Providers (stored encrypted) or in api/.env: `DEEPGRAM_API_KEY` (fast English listening and English voices;
listening also understands Tamil, and Tamil lines are spoken by the browser), `SARVAM_API_KEY` (Tamil and Indian
English voices), `OPENAI_API_KEY`, or `GOOGLE_CLOUD_API_KEY`.

**Live conversation (Ask Aasan):** set **Listening = Deepgram** with a key. Hands-free then becomes a live,
interruptible conversation: the browser streams 16 kHz audio over `ws/voice-stream/` (proxied by the existing `/ws/`
nginx block), and the API streams it on to Deepgram Nova-3 (`en-IN` or `ta`); the key stays on the server. It is
charged from the real audio length against the plan's voice minutes and the provider's `stt_seconds_per_day`, and one
stream closes after `VOICE_STREAM_MAX_MINUTES` (default 30; the app reconnects). The API host needs outbound access to
`wss://api.deepgram.com`. With any other Listening provider, hands-free keeps working the old way (paused while Aasan
talks).

**Google sign-in (optional):** in Google Cloud Console → APIs & Services → Credentials → Create credentials →
OAuth client ID → Web application, add the site URL (`https://<domain>`, no path; `http://localhost:5173` for dev) as
an **Authorised JavaScript origin**, then set `GOOGLE_CLIENT_ID=<the client ID>` in api/.env and restart the API. The
page reads it from `GET /api/users/auth-config/`; until it is set, no Google button is shown.

**Web push (optional):** `uv run python manage.py setup_env` writes a VAPID key pair (`WEBPUSH_VAPID_PUBLIC_KEY`,
`WEBPUSH_VAPID_PRIVATE_KEY`) into api/.env when neither is set; on an existing install, delete both lines and run it
again, or paste a pair made with `vapid --gen` (py-vapid). Set `WEBPUSH_VAPID_SUBJECT=mailto:support@<domain>`.
Keep the pair stable: a new pair ends every learner's existing subscription. Push needs HTTPS (or
`http://localhost`) and outbound HTTPS from the Celery worker to the browsers' push services; endpoints outside
`WEBPUSH_ENDPOINT_HOSTS` are refused. Without both keys the "Turn on notifications" card stays hidden. Celery beat runs
`evening-checks` every 30 min (acts 18:00-21:00) and `winback-daily` at 10:30.

**Organisation SSO (per organisation, no server setting):** each organisation sets it up in its cockpit → Settings →
"Sign in with your organisation (SSO)". The redirect URI is always `FRONTEND_URL` + `/sso/callback`
(`https://<domain>/sso/callback`), so `FRONTEND_URL` must be the public HTTPS address before anyone registers it.
- *Google Workspace:* Google Cloud Console → APIs & Services → Credentials → Create credentials → OAuth client ID →
  Web application; add `https://<domain>/sso/callback` under **Authorised redirect URIs**; set the OAuth consent screen
  to **Internal** (Workspace users only). Paste the client ID and secret into the cockpit.
- *Microsoft Entra ID:* Entra admin centre → App registrations → New registration → "Accounts in this organizational
  directory only" (single tenant); Redirect URI → Web → `https://<domain>/sso/callback`; Certificates & secrets → New
  client secret; API permissions: `openid`, `email`, `profile` (Microsoft Graph, delegated). Token configuration → add
  the optional `email` claim to the ID token. Paste the Application (client) ID, the secret value and the Directory
  (tenant) ID; `common` / `organizations` are refused.
- *Domains:* the cockpit shows a DNS TXT record `aasan-verify=<token>` to add at the domain itself or at
  `_aasan.<domain>`; press Verify once it has propagated. A daily job (`sso-domain-recheck`) re-checks it and
  un-verifies a domain after 7 days without the record (enforcement stops when no verified domain is left).
- *Require SSO* (owners only) refuses password sign-in and sign-up for those domains; owners keep their password as a
  break-glass and passkeys keep working. Platform support can switch an organisation's SSO off in Admin console →
  Organisations → (the organisation) → Switch SSO off.
- The server makes outbound HTTPS calls to `accounts.google.com`, `oauth2.googleapis.com`, `www.googleapis.com` and
  `login.microsoftonline.com` (token exchange and signing keys), and DNS TXT lookups for domain checks.

**Public address** (infra/.env):

| Var | Production value |
|---|---|
| `FRONTEND_URL` | `https://<domain>` |
| `WEBAUTHN_ORIGIN` | `https://<domain>` |
| `WEBAUTHN_RP_ID` | `<domain>` (bare host) |
| `DJANGO_ALLOWED_HOSTS` | `<domain>,localhost,127.0.0.1,api,web` |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` once HTTPS is in front |
| `DJANGO_NUM_PROXIES` | `1` (nginx only) or `2` (a cloud load balancer, then nginx) |
| `WEB_PORT` | the host port nginx listens on (default 8080) |
| `WEB_BIND` | the host address it binds to (default `127.0.0.1`; `0.0.0.0` only behind a firewall that admits just the LB) |

**Refused at startup.** With `DJANGO_DEBUG` off and a non-local `FRONTEND_URL`, the API (and the voice agent) will not
start while any of these is unsafe: `FRONTEND_URL` not `https://`, `DJANGO_ALLOWED_HOSTS` only local hosts,
`DJANGO_SECRET_KEY` under 50 characters, `AASAN_SECRETS_KEY` missing, LiveKit on its public dev pair (or a secret
under 32 characters), `SENTRY_DSN` unset (unless `SENTRY_OPTIONAL=1`), or `api/.env` readable by other users
(`chmod 600 api/.env`). The error lists every problem.

**Secrets from files.** Any setting can be read from a file instead of `api/.env`: set `NAME_FILE=/run/secrets/name`
(Docker secrets, or a secret manager's mounted file), e.g. `AASAN_SECRETS_KEY_FILE`, `DJANGO_SECRET_KEY_FILE`,
`EMAIL_HOST_PASSWORD_FILE`, `LIVEKIT_API_SECRET_FILE`. Keep the off-host escrow copy of `AASAN_SECRETS_KEY` apart from
the backups: whoever has both can read every stored provider key. The local stack on `http://localhost:8080` is not affected.

**Ops** (api/.env or infra/.env):

| Var | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | root log level |
| `LOG_FORMAT` | `json` with DEBUG off | `json` (one object per line) or `plain` |
| `SLOW_REQUEST_MS` | `1000` | requests slower than this are logged as warnings with their request id |
| `HEALTH_TIMEOUT` | `2` | seconds allowed for each readiness check |
| `SENTRY_DSN`, `SENTRY_TRACES` | required on a public site, `0` | error monitoring (no personal data is sent); `SENTRY_OPTIONAL=1` runs without it on purpose |
| `METRICS_TOKEN` | — | bearer token for `/api/metrics/` (Prometheus, see "Monitoring" below); empty = off |
| `HEALTH_CACHE_SECONDS` | `5` | readiness answers reused this long; nginx also limits `/api/health/` to 60/min per IP |
| `LLM_FALLBACK`, `LLM_BREAKER_SECONDS` | —, `60` | providers to fail over to when the configured one is rate-limited or down (e.g. `gemini,openai`) |
| `LLM_MONTHLY_BUDGET` | `0` | rupees; staff get an email at 50/80/95% of this month's AI cost |
| `VOICE_LIVE_MAX_CALLS` | `12` | live voice calls per host at once (each 200–400 MB in `voice-agent`); over it voice falls back to streamed listening |
| `*_RETENTION_DAYS` | 365 / 365 / 400 / 180 | mentor chats, role-play transcripts, AI usage rows, speech clips (nightly `data-retention`; 0 = keep) |
| `SECURITY_REDIS_URL` | `REDIS_URL` server, DB 3 | lockouts, OTP tries, mail caps: must never evict (not `redis-cache`) |
| `DJANGO_ADMINS` | — | staff emails for server errors and payment alerts |
| `DJANGO_HSTS_SECONDS` | `31536000` | one year; HTTPS must work before go-live (a public site has to be https anyway) |
| `ADMIN_REAUTH_MINUTES` | `30` | admin console changes need a sign-in within this window (the console asks again); `0` = off |
| `STAFF_SECOND_FACTOR` | `true` | that sign-in must be a passkey or an emailed code, not a password alone (the password still counts until email works) |
| `PASSWORD_BREACH_CHECK` | `true` | refuse passwords found in public breaches (HIBP k-anonymity; fails open) |
| `VOICE_LIVE_MAX_MINUTES` | `30` | a live voice call ends after this long; the learner can start another |
| `VOICE_AGENT_MEMORY` | `4g` | memory cap for the voice-agent container (about 200–400 MB per simultaneous call) |
| `BACKUP_COPY_CMD` | — | (infra/.env) run by `infra/backup.sh` after each backup to copy it off the server; a failure fails the backup |
| `BACKUP_AGE_RECIPIENT` | — | (infra/.env) age public key or recipients file; backups are encrypted to it |
| `BACKUP_REQUIRE_OFFSITE` | `1` | `infra/backup.sh` refuses to run without the two settings above |
| `BACKUP_ALLOW_LOCAL` | `0` | `1` = dev only: local, possibly unencrypted backups, with a warning |
| `BACKUP_AGE_IDENTITY` | — | private key file for `infra/restore.sh`; never stored on the server (section 7) |
| `WALG_S3_PREFIX`, `AWS_*` | — | (infra/.env) only with the PITR overlay `infra/docker-compose.pitr.yml` (section 7.3) |

**Security events.** Sign-ins, failed passwords, lockouts, password resets, passkey changes, re-authentication and
admin changes refused for an old sign-in are logged on logger `aasan.security`, with an `event` field and the account
as a short hash of the email (no addresses in the logs). Alert on bursts of `account_locked` or `passkey_failed`.

Every response carries `X-Request-ID`. nginx forwards the caller's id, or creates one, and logs it as `rid=`. Django
logs it in every line, so you can grep one id across nginx and the API.

Scaling knobs are in section 8.

### Live voice (self-hosted LiveKit)

Live voice (talk to Aasan like a phone call, on Ask Aasan, Live Class, Role-play and workshops) is a self-hosted
LiveKit server plus Aasan's voice agent, both in the compose file behind `--profile voice`. It needs no LiveKit
account. It needs a Sarvam key (Admin → Providers, Speaking or Listening = Sarvam); Claude still writes every answer.

    docker compose -f infra/docker-compose.yml --profile voice up -d

- **Keys:** locally LiveKit's dev pair (`devkey` / `secret`) is the default. In production set your own
  `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` (secret: `openssl rand -hex 32`) in `infra/.env`; the same pair reaches the
  livekit server, the API and the agent. The API and agent refuse to start on the dev pair once the site is public.
- **Network:** signalling goes through nginx at `/livekit/`. Set `LIVEKIT_PUBLIC_URL=wss://<domain>/livekit`. Media
  needs **UDP 7882** (and TCP 7881 as the fallback) open to the internet, and `LIVEKIT_NODE_IP=<public IP>` (or
  `LIVEKIT_USE_EXTERNAL_IP=true`).
- **TURN (learners behind firewalls that block UDP: offices, schools, some mobile carriers):** without it their calls
  can't connect and their screens quietly keep the browser voice. Turn on LiveKit's built-in TURN: a DNS name
  (`turn.<domain>`) with a certificate (`turn.crt` full chain + `turn.key`), then in `infra/.env`
  `LIVEKIT_TURN_ENABLED=true`, `LIVEKIT_TURN_DOMAIN=turn.<domain>`, `LIVEKIT_TURN_CERTS=<folder>`, open **5349/tcp**
  and **3478/udp**, and start with the add-on file:
  `docker compose -f infra/docker-compose.yml -f infra/docker-compose.turn.yml --profile voice up -d`.
  The few networks that allow only 443 need TURN on 443, which needs its own IP (443 is taken by HTTPS).
- **Limits:** a call lasts at most `VOICE_LIVE_MAX_MINUTES`; each learner has one call at a time (a new one ends the
  old); the join token only allows a microphone track; voice minutes and the Sarvam budget are charged as it runs.
- **Another LiveKit on the host:** move ours with `LIVEKIT_TCP_PORT` / `LIVEKIT_UDP_PORT` (the same number is used
  inside and outside the container).
- **Capacity:** one agent job (a process) per live call, roughly 200–400 MB each with the turn-detector model. Run
  more `voice-agent` replicas on a separate host for many simultaneous calls.
- **Without it:** `/api/voice/config/` reports `live: false` and every screen keeps the browser or Deepgram voice.

## 4. HTTPS and the domain

The `web` container speaks plain HTTP on `WEB_PORT`. Never expose it directly to the internet; put a TLS terminator
in front that sets `X-Forwarded-Proto`. Two options:

- **Caddy on the same host** (automatic Let's Encrypt). Its whole config is
  `<domain> { reverse_proxy 127.0.0.1:8080 }`. `web` binds to `127.0.0.1` by default (`WEB_BIND`), so only Caddy
  reaches it.
- **A cloud load balancer.** Set `DJANGO_NUM_PROXIES=2` and `WEB_BIND=0.0.0.0`, and allow only the load balancer to
  reach `WEB_PORT`. nginx
  rate-limits sign-in by client IP. Behind a load balancer, add `set_real_ip_from <LB CIDR>; real_ip_header
  X-Forwarded-For;` to `infra/nginx/default.conf`. Otherwise every user shares the load balancer's IP, and the login
  limit applies to all of them together.

DNS: an `A` record (and `AAAA` for IPv6) for `<domain>` pointing at the host or the load balancer. Then set the
public-address variables in section 3 and run `docker compose -f infra/docker-compose.yml up -d`.

Check it:

```sh
curl -sI https://<domain>/ | grep -i strict-transport
curl -fsS https://<domain>/api/health/ready/
```

## 5. Razorpay live keys and the webhook

1. Razorpay dashboard: complete KYC and generate **live** keys.
2. Aasan admin console, **Payments & plans**: enter the live Key ID, Key Secret and Webhook Secret, then switch on
   **Allow live payments**. Live keys are refused until that switch is on. The `RAZORPAY_*` values in `api/.env` are
   only a fallback.
3. Razorpay dashboard, **Webhooks**, add `https://<domain>/api/billing/webhook/` with the same secret. Subscribe to
   `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`, `refund.failed` and the `subscription.*`
   events. Without the refund events, refunds sent from **Admin → Refunds** stay "pending" in the console even after
   Razorpay settles them.
4. Test with a small real payment, then refund it. Beat runs `payment-reconcile` every 10 minutes and grants anything
   Razorpay captured but the webhook missed.

## 6. Email (SMTP) and Sentry

- **SMTP.** Either set it in the admin console (**Email (SMTP)**), which wins, or set `EMAIL_HOST`, `EMAIL_PORT`,
  `EMAIL_USE_TLS=true`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` in `infra/.env`. With
  neither, mail goes to mailpit. That is right for local work and wrong in production, so stop the `mailpit` service
  or ignore it. Set up SPF, DKIM and DMARC for the sending domain with your mail provider.
- **Sentry.** Set `SENTRY_DSN` in `api/.env`. Optionally set `SENTRY_TRACES=0.05` for performance sampling.
- **Lesson media and voices.** Podcast, explainer video and "Listen to this lesson" are off until switched on in
  **Lesson media**. Voices are set in **AI & Voice providers**: "Speaking" for English (recommended Deepgram Aura-2)
  and "Speaking: Tamil" (recommended Sarvam bulbul:v4-flash), each with its own key, narrator voice and the two podcast
  host voices. Spoken lines are generated once and stored in the media volume under `speech/`; nginx serves them from
  `/api/media/speech/` with a one-year immutable cache, so include that folder in media backups (it can also be
  deleted at any time: lines are re-made on demand).

## 7. Backups and the restore drill

**Targets.**

| | Nightly dumps only | + PITR overlay, or managed Postgres with PITR |
|---|---|---|
| RPO (data you can lose) | up to 24 h | about 5 min |
| RTO (time to be back up) | about 1 h | about 1 h |

The RTO assumes the restore steps below are practised (the monthly drill) and the age key is reachable.

### 7.1 Nightly encrypted dumps (always)

`infra/backup.sh` streams `pg_dump -Fc` and a tarball of the media volume through [age](https://age-encryption.org)
into `./backups`, so only `db-STAMP.dump.age` and `media-STAMP.tgz.age` ever touch the disk, writes
`manifest-STAMP.sha256` next to them, keeps 14 days locally (`BACKUP_KEEP_DAYS`), and then runs `BACKUP_COPY_CMD` to
copy them off the server. Any failure (dump, media, encryption, copy) exits non-zero.

By default (`BACKUP_REQUIRE_OFFSITE=1`) it refuses to run, before dumping anything, unless both
`BACKUP_AGE_RECIPIENT` and `BACKUP_COPY_CMD` are set. `BACKUP_ALLOW_LOCAL=1` is the opt-out for a dev machine: local
only, unencrypted if no recipient is set, and it prints a warning every run. Never use it in production.

**One-time setup.**

1. Install age on the host: `apt install age` (or `brew install age`).
2. Make the key pair **on your laptop or a password manager machine, not on the server**:

   ```sh
   age-keygen -o aasan-backup.key        # prints "Public key: age1..."
   ```

   The private key file (`aasan-backup.key`) is the only way to read the backups. Keep it off the host: a password
   manager (1Password / Bitwarden secure note), plus a printed or USB copy in a safe. Never store it next to the
   backups, in the bucket, in `api/.env`/`infra/.env`, or in the repo. Two people should be able to get to it.
3. In `infra/.env` set the public half and the copy command (the script reads `BACKUP_*` lines from `infra/.env`;
   the environment wins):

   ```sh
   BACKUP_AGE_RECIPIENT=age1...                   # or a path to a recipients file (one key per line, e.g. two admins)
   BACKUP_COPY_CMD=rclone copy ./backups r2:aasan-backups/nightly
   ```

**Off-server copy examples.** The command runs with `BACKUP_DIR` and `BACKUP_STAMP` exported.

- **Cloudflare R2 / AWS S3 / Backblaze B2 with rclone.** `rclone config` a remote with a key that can *write* to one
  bucket but not delete. Turn on **object lock** (S3/B2: bucket created with Object Lock, default retention in
  compliance or governance mode, e.g. 35 days; R2: a bucket lock rule) so a compromised server can't erase history.
  Use `rclone copy` (never `sync`, which deletes) and set a lifecycle rule to expire objects after, say, 90 days.

  ```sh
  BACKUP_COPY_CMD=rclone copy --immutable ./backups r2:aasan-backups/nightly
  ```

- **AWS CLI:** `BACKUP_COPY_CMD=aws s3 sync ./backups s3://aasan-backups/nightly/` (no `--delete`; the bucket's
  lifecycle rule handles expiry).
- **Another machine over SSH:** a dedicated `backup` user on the other host, key-only, ideally with an
  `rrsync`-restricted `authorized_keys` entry so it can only write into one folder:

  ```sh
  BACKUP_COPY_CMD=rsync -a ./backups/ backup@vault.example.com:aasan/
  ```

**Cron** (from the repo root; the script needs bash, docker and age):

```cron
15 2 * * *  cd /srv/aasan && bash infra/backup.sh >> /var/log/aasan-backup.log 2>&1
```

Alert on failure: send that log to your monitoring, or wrap the line with a dead-man's switch (e.g.
`... && curl -fsS https://hc-ping.com/<uuid>`) so a backup that *didn't* run is noticed too.

### 7.2 Restore and the monthly drill

`infra/restore.sh` takes a backup stamp (looked up in `./backups`) or the path to a `db-*.dump.age` file, checks the
sha256 manifest, decrypts with `BACKUP_AGE_IDENTITY` (the private key file) and runs
`pg_restore --clean --if-exists`. The default target is a scratch database, `aasan_restore_check`, so a drill never
touches the live data. Copy the key onto the server only for the restore, and delete it afterwards.

**Restore drill (monthly, and before go-live).** Pull last night's backup *from the off-server copy* (that is what
you would have after losing the server), then:

```sh
rclone copy r2:aasan-backups/nightly ./drill --include "*20261030-021500*"     # the newest stamp
BACKUP_DIR=./drill BACKUP_AGE_IDENTITY=~/aasan-backup.key bash infra/restore.sh --drill 20261030-021500
#   ... restore: aasan_restore_check has 1234 users, 180 applied migrations
#   drill ok: backup 20261030-021500 restored, checked and dropped
rm -rf ./drill ~/aasan-backup.key
```

`--drill` restores into the scratch database, counts `accounts_user`, and drops it. Add `--media-dir /tmp/media-check`
to unpack the media too. Write the date, backup stamp, user count and time taken in the ops log; if the drill fails,
fix it before anything else.

**Real restore** (data loss: stop writers first):

```sh
C="docker compose -f infra/docker-compose.yml"
$C stop api worker beat
BACKUP_AGE_IDENTITY=~/aasan-backup.key bash infra/restore.sh --target-db aasan --force --media-volume 20261030-021500
$C up -d
```

Restoring into `aasan` needs `--force`. `--media-volume` unpacks the media tarball into the api container's
`/app/media`.

### 7.3 Point-in-time recovery (optional, RPO about 5 min)

Two ways to get from a 24-hour to a roughly 5-minute RPO:

- **Managed Postgres with PITR** (AWS RDS/Aurora, Google Cloud SQL, Azure Flexible Server, Neon, Crunchy Bridge,
  DigitalOcean): turn on PITR with at least 7 days' retention, point `DATABASE_URL` at it and drop the `db` service.
  Keep the nightly dump too (set `BACKUP_COMPOSE` or run `pg_dump` against the managed host).
- **Self-hosted: `infra/docker-compose.pitr.yml`.** It rebuilds `db` as `postgres:16-alpine` + WAL-G
  (`infra/postgres-walg/`), turns on `archive_mode` with `archive_command = wal-g wal-push %p` and
  `archive_timeout=300`, and adds a `walg-backup` sidecar that takes a full base backup daily and keeps the last 7
  (`WALG_RETAIN_FULL`). Set `WALG_S3_PREFIX`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and, for R2/B2/MinIO,
  `AWS_ENDPOINT`/`AWS_REGION` in `infra/.env`; use a separate bucket from the nightly dumps. Recommended: client-side
  encryption with a PGP public key in `infra/walg-keys/pgp.pub` and `WALG_PGP_KEY_PATH=/etc/walg/pgp.pub`.

  ```sh
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.pitr.yml up -d --build
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.pitr.yml exec -u postgres db wal-g backup-list
  ```

  Use both `-f` files on every compose command from then on (or set `COMPOSE_FILE=infra/docker-compose.yml:infra/docker-compose.pitr.yml`).
  If the archive bucket is unreachable Postgres keeps WAL locally and retries, so watch disk space and the
  `walg-backup` health status.

  **PITR restore** (to a new, empty data volume; the old one stays untouched for safety):

  ```sh
  C="docker compose -f infra/docker-compose.yml -f infra/docker-compose.pitr.yml"
  $C stop api worker beat walg-backup db
  docker volume create aasan_pgdata_restore
  docker run --rm --env-file <(grep -E '^(WALG_|AWS_)' infra/.env) -v aasan_pgdata_restore:/var/lib/postgresql/data \
    -u postgres aasan-postgres-walg:16 sh -c '
      wal-g backup-fetch /var/lib/postgresql/data LATEST &&
      touch /var/lib/postgresql/data/recovery.signal &&
      printf "%s\n" "restore_command = '\''wal-g wal-fetch %f %p'\''" \
                    "recovery_target_time = '\''2026-10-30 14:05:00+05:30'\''" \
                    "recovery_target_action = promote" >> /var/lib/postgresql/data/postgresql.auto.conf'
  ```

  Then point the `db` service at `aasan_pgdata_restore` (override `volumes:` or swap the volume names), start `db`
  alone, wait for "database system is ready to accept connections" and check the data, then start the rest. Drill
  this once per quarter, on a spare host.

## Monitoring

`infra/docker-compose.monitoring.yml` adds Prometheus (scrapes `api:8000/api/metrics/` inside Docker; public nginx
answers 404 there), Alertmanager (email), Grafana (127.0.0.1:3000, reach it over an SSH tunnel) and Loki + Promtail
(every container's logs, 90 days, including `aasan.security` events).

```sh
openssl rand -hex 24 | tee infra/monitoring/metrics_token    # chmod 600; the same value goes in infra/.env:
#   METRICS_TOKEN=<that value>  ALERT_EMAIL_TO=ops@<domain>  ALERT_SMTP_HOST=smtp.<provider>:587  ALERT_SMTP_USER=…
#   ALERT_SMTP_PASSWORD=…  GRAFANA_ADMIN_PASSWORD=…
docker compose -f infra/docker-compose.yml -f infra/docker-compose.monitoring.yml up -d
```

Alerts (`infra/monitoring/alerts.yml`): API not answering, Celery queue over 200 for 10 min, more than 10 failed
jobs in 15 min, under 20% disk, Redis over 70% memory or down, Postgres over 80% connections, more than 20 AI
provider errors in 10 min, organisation webhooks failing. Also point an outside uptime check (UptimeRobot, Better
Stack) at `https://<domain>/api/health/ready/`, which catches the host itself going down. A useful Grafana search for
attacks: `{service="api"} |= "account_locked"`.

**Celery beat runs on one node only.** A second beat exits at start-up (it holds a lock in the broker Redis), so a
copied compose file on a second VM can't double-send reminders. Run `beat` on exactly one machine.

## 8. Scaling knobs

| Knob | Default | Notes |
|---|---|---|
| `WEB_CONCURRENCY` | min(2 × CPU + 1, 9) | API processes. Each runs an async event loop, so one process holds many WebSockets |
| `DB_POOL_MIN` / `DB_POOL_MAX` | 2 / 10 | Postgres pool **per API process** (Django 5.2 psycopg pool) |
| `DB_POOL_TIMEOUT` | 10 s | wait for a free pooled connection before erroring |
| `DB_STATEMENT_TIMEOUT_MS` | 30000 | per-statement cap for the API. The migrate job uses 0 (no cap) |
| `CELERY_CONCURRENCY` | 4 | worker children. Run more `worker` replicas for more throughput |
| `WORKER_DB_POOL_MAX` | 3 | pool per Celery child |
| `WORKER_DB_STATEMENT_TIMEOUT_MS` | 120000 | statement cap for tasks |
| `CELERY_SOFT_TIME_LIMIT` / `CELERY_TIME_LIMIT` | 900 / 960 s | per task |
| `CHANNELS_CAPACITY` / `CHANNELS_EXPIRY` / `CHANNELS_GROUP_EXPIRY` | 1000 / 60 s / 86400 s | channel layer limits |
| `PG_MAX_CONNECTIONS` | 300 | Postgres server limit |
| `PG_SHARED_BUFFERS` / `PG_EFFECTIVE_CACHE_SIZE` | 1GB / 4GB | use 4GB / 12GB on a dedicated 16 GB database host |
| `REDIS_MAXMEMORY` / `REDIS_CACHE_MAXMEMORY` | 512mb / 256mb | broker + channels (noeviction) / cache (LRU) |
| `GUNICORN_MAX_REQUESTS` (+ `_JITTER`) | 0 = off (+500) | recycles a worker after N requests. Off by default: recycling drops that worker's live WebSockets (close 1012). Turn on only if worker memory creeps up |
| `WS_PING_INTERVAL` / `WS_PING_TIMEOUT` | 20 / 20 s | WebSocket keepalive. nginx allows a socket to be idle for 1 h |

**Connection budget.** Keep this sum below `PG_MAX_CONNECTIONS`, with headroom for `psql` and backups:

    WEB_CONCURRENCY × DB_POOL_MAX + CELERY_CONCURRENCY × WORKER_DB_POOL_MAX + 2 (beat) + 2 (migrate)

With the defaults on 8 cores: 9 × 10 + 4 × 3 + 4 = 106, well under 300. A request holds a connection only while it
runs (`CONN_MAX_AGE=0` returns it to the pool).

**Reliability defaults.**
- Celery acknowledges a task only after it finishes (`acks_late`), so a task from a crashed worker goes back to the
  queue.
- Each child prefetches one task.
- Email and notification tasks retry transient failures (database, Redis or SMTP down) with exponential backoff:
  5 tries, at most 10 min apart.
- nginx limits sign-in, sign-up and password reset to 30 requests per minute per IP, with a burst of 30, and returns
  429 above that. Django throttles these too.

## 9. Capacity notes

Measured on 18 Oct 2026 with `api/scripts/load_test.py` against this compose stack on one 8-core / 16 GB laptop (the
Docker VM had 8 vCPU / 8 GB, and the load generator ran on the same machine). AI was the fake provider with real-model
latency (800 ms to first token, then streamed), so no API spend.

**500 concurrent users** (300 browsing, 100 in mentor chat, 100 in live workshop sessions; 60 s ramp, 5 min hold):
- HTTP: 20,452 requests, **0 errors**; p95 under 50 ms and p99 under 100 ms on every endpoint (me, today, courses,
  lessons, review, paths, workshops, certificates).
- WebSockets: 200 of 200 connected, 0 failed; connect p50 3 ms.
- Resources at peak: API about 1.5 vCPU and 1.2 GB across 9 workers; Postgres about 0.5 vCPU and 200 MB; Redis negligible.

**Fixes the load test drove** (all in the code and covered by tests):
1. Socket sync work shared one thread per worker, so one learner's AI grading stalled every other socket and AI replies
   had 20–60 s tails. Each connection now gets its own thread context (`config/asgi_threads.py`). The p95 to first token
   dropped from 22 s to 1.6 s.
2. Pooled DB connections sat idle behind slow AI calls until requests failed with PoolTimeout. Sync AI calls now hand the
   connection back first (`llm/dbconn.py`).
3. Worker recycling (`max_requests`) dropped live sockets (close 1012) every few minutes. It is now off by default.
4. Channels on redis-py 8: the client's 5 s read timeout equalled the channel layer's 5 s blocking wait, so every idle
   socket died. The read timeout is now 30 s (`CHANNELS_SOCKET_TIMEOUT`), and readiness pings Redis instead of doing a
   receive.
5. Postgres rejected `SELECT ... FOR UPDATE` with nullable joins (payments, subscriptions, guest claims): 500s after
   money was taken. Locks now use `of=("self",)`, with a guard test.

Later runs on the same laptop were not usable as numbers: the full test suite and a headless browser suite ran on it at
the same time (load average 40–80 on 8 cores).

**Recommended production size for 500+ concurrent users:**
- App: one 8 vCPU / 16 GB VM (`WEB_CONCURRENCY=9`, `DB_POOL_MAX=10`), or two 4 vCPU / 8 GB VMs behind a load balancer
  (`WEB_CONCURRENCY=5` each). Two VMs give you zero-downtime deploys and survive one VM failing.
- Postgres: managed, 2 vCPU / 4–8 GB, `max_connections` at least workers × `DB_POOL_MAX` + Celery + 20.
- Redis: managed or the bundled container, 1 GB, with noeviction for the broker and channels.
- Celery: `CELERY_CONCURRENCY=4` (course generation and emails), on the app VM or a small separate one.
- For about 2,000+ concurrent users, add app VMs (the app is stateless; sockets fan out through Redis) and size Postgres up.

**The real limit is the AI provider, not this stack.** 100 people chatting at once is about 3–6 model calls a second.
Check your Anthropic tier's requests-per-minute and tokens-per-minute limits, and the monthly spend cap, before launch.
A spend cap was hit once in October 2026. The app degrades gracefully: rate-limit and quota errors show a friendly retry
message and refund the learner's message quota. Per-plan daily limits (`apps/billing` plan limits) bound the cost per
learner.

## 10. Deploying an update and rolling back

Production runs images that CI built and pushed to GHCR (`.github/workflows/release-images.yml`, on every `v*` tag):
`ghcr.io/<owner>/aasan-api:<tag>` and `ghcr.io/<owner>/aasan-web:<tag>`, each also tagged `sha-<short commit>`, with
provenance and an SBOM attached. The server only pulls; `TAG` in `infra/.env` says which release runs. Ship every
release through staging first (section 11).

**Deploy from registry (update):**

```sh
git fetch && git checkout <release-tag>              # compose file, nginx and scripts of the same release
bash infra/backup.sh                                 # always, before migrations
#   set TAG=<release-tag> in infra/.env (note the old value: it is the rollback target)
docker compose -f infra/docker-compose.yml pull
docker compose -f infra/docker-compose.yml up -d --no-build
docker compose -f infra/docker-compose.yml ps        # wait for "healthy"
curl -fsS https://<domain>/api/health/ready/
```

`--no-build` makes sure nothing is ever compiled on the production host: if an image is missing from the registry,
`up` fails instead of quietly building one.

`migrate` runs before the new API starts. Write migrations so the previous release still works on the new schema
(add columns nullable or with defaults, and drop columns in a later release). Then a rollback needs no database
restore.

**Rollback:**

1. Code only (no migration, or a backwards-compatible one): set `TAG` in `infra/.env` back to the previous release
   (the images are still in the registry, and usually still on the host), then:

   ```sh
   git checkout <previous-tag>
   docker compose -f infra/docker-compose.yml pull
   docker compose -f infra/docker-compose.yml up -d --no-build
   ```

2. A migration must be undone. Do this **before** step 1, while `TAG` is still the new release (only its image has
   the newer migration files). Find the previous migration name per app in the old release, then:

   ```sh
   docker compose -f infra/docker-compose.yml run --rm migrate python manage.py migrate <app> <previous_migration>
   ```

   Then do step 1.
3. The data is damaged. Restore the pre-deploy dump (section 7, real restore), then do step 1.

**Fallback: build on the host.** If the registry is unreachable or CI is down and a fix can't wait, build the images
on the server from the checked-out release and give them a tag that says so:

```sh
git checkout <release-tag>
#   in infra/.env: TAG=<release-tag>-local and AASAN_IMAGE_PREFIX empty (local image names aasan-api / aasan-web)
docker compose -f infra/docker-compose.yml up --build -d
```

Go back to registry images with the next release. Images built this way were not scanned by CI.

**Release notes for the adaptive learning + admin roles release** (migrations `accounts.0007`, `adaptive.0001`,
`billing.0010`, `orgs.0011`, `credentials.0004`; all additive, so rolling back the code needs no database restore):

- Staff accounts that existed before keep full access (they count as superadmins). Narrow them in
  **Admin → Staff & audit log** after the deploy.
- Add the two refund events to the Razorpay webhook (section 5).
- Existing courses get a simple concept map the first time a learner opens them (no AI cost); new courses get an AI
  concept map when they are generated. Learners get their own path the first time they open a course, which turns on
  practice-before-finishing for lessons below the pass mark.

After a rollback, check `/api/health/ready/`, sign in, open the mentor chat (WebSocket), and make a test payment in
test mode if billing changed.

**Fallback API server.** If gunicorn or uvicorn misbehaves, set
`API_COMMAND=daphne -b 0.0.0.0 -p 8000 config.asgi:application` in `infra/.env` and run
`docker compose -f infra/docker-compose.yml up -d api`. It runs a single process, so expect lower capacity.

## 11. Staging and release runbook

Staging is the production stack plus `infra/docker-compose.staging.yml`: the fake AI provider (no paid model is ever
called), Razorpay **test** keys only, its own compose project (`aasan-staging`: separate containers, network and
volumes), its own ports (nginx 8090, mailpit 8026/1026 on 127.0.0.1) and a smaller memory profile. It runs the very
images production will run, so a release is tested once and promoted as is.

**One-time staging setup** (a small separate VM is best; the same host as production also works, as the ports,
volumes and settings files are all separate):

```sh
cp infra/staging.env.example infra/staging.env      # gitignored; passwords, TAG, AASAN_IMAGE_PREFIX, staging URL,
                                                   # STAGING_RAZORPAY_* test keys (rzp_test_...)
# App settings for staging: its own secret keys, never production's api/.env
cp api/.env.example api/.env.staging && chmod 600 api/.env.staging
#   set DJANGO_SECRET_KEY and AASAN_SECRETS_KEY in it to fresh values (openssl rand -hex 32 for each)
S="docker compose --env-file infra/staging.env -f infra/docker-compose.yml -f infra/docker-compose.staging.yml"
```

Give staging its own host name (for example `staging.<domain>`) in Caddy, proxying to `127.0.0.1:8090`, and set
`FRONTEND_URL`, `WEBAUTHN_ORIGIN`, `WEBAUTHN_RP_ID` and `DJANGO_ALLOWED_HOSTS` in `infra/staging.env` to match.
Keep it out of search engines and behind basic auth or an IP allowlist if it must not be public.

**Release:**

1. **Tag.** On `main`, after CI is green for that commit:

   ```sh
   git tag -a v1.3.0 -m "Aasan 1.3.0" && git push origin v1.3.0
   ```

2. **CI images.** The tag starts **Release images** (`.github/workflows/release-images.yml`), which builds and pushes
   `ghcr.io/<owner>/aasan-api:v1.3.0` and `aasan-web:v1.3.0` (plus `sha-<short>`). Wait for it to go green. The
   regular CI run on `main` has already scanned the same Dockerfiles (Trivy, HIGH and CRITICAL with a fix fail) and
   uploaded CycloneDX SBOMs as the `sbom-cyclonedx` artifact.
3. **Deploy to staging.** Set `TAG=v1.3.0` in `infra/staging.env`, then:

   ```sh
   git fetch && git checkout v1.3.0
   $S pull && $S up -d --no-build
   $S ps                                            # every service "healthy" (migrate "exited (0)")
   ```

4. **Smoke checks on staging:**
   - `curl -fsS https://staging.<domain>/api/health/ready/` returns `{"ok": true, ...}`.
   - `$S exec api printenv LLM_FORCE_PROVIDER` prints `fake`.
   - Sign in (email + password, and a passkey if you use them) and open the dashboard.
   - Open the mentor (Kili), send one message, and get the canned demo reply streamed back over the WebSocket.
   - If billing changed: one test-mode checkout with a Razorpay test card, and the webhook marks it paid.
   - `$S logs --since 10m api worker | grep -i error` shows nothing new.
5. **Promote the same TAG to production.** Nothing is rebuilt: follow "Deploy from registry" in section 10 with
   `TAG=v1.3.0` in `infra/.env`. Run the first smoke check against `https://<domain>`, then sign in and open the
   mentor once (production answers with the real model).
6. **Rollback.** Set `TAG` back to the previous release in `infra/.env` and run `pull` + `up -d --no-build` (section
   10, rollback; undo any migration first, while the new TAG is still set). The previous images stay in GHCR, so a
   rollback needs no build. Roll staging back the same way with `infra/staging.env`.

A hotfix follows the same path with a patch tag (`v1.3.1`). To try a branch on staging without a release, run
**Release images** by hand (workflow_dispatch) with a tag such as `v1.3.1-rc1`, and set that TAG on staging only.
