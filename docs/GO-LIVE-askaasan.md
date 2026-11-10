# Go-live sheet: askaasan.com

The domain-specific values for putting Aasan on **https://askaasan.com**. The full runbook is
[DEPLOY.md](DEPLOY.md); this sheet fills in its `<domain>` blanks and lists what to check before announcing.
Release: **1.3.0** on `main` (tag `v1.3.0`): live voice, guardrails, web search in every voice conversation, course map
and the gap-review hardening. To build on the server from the source package instead of pulling CI images, follow
[SERVER-HANDOFF.md](SERVER-HANDOFF.md) (`infra/init-env.sh` writes both `.env` files; `TAG=v1.3.0-local`).

`https://askaasan.com` is the only address. `www.askaasan.com` redirects to it (see `infra/Caddyfile`), because
passkeys, sign-in cookies and the OAuth redirect URIs are all tied to one origin.

## 1. DNS

| Record | Name | Value |
|---|---|---|
| A (and AAAA for IPv6) | `askaasan.com` | the server's public IP |
| A / CNAME | `www.askaasan.com` | the same server (Caddy redirects it) |
| A | `turn.askaasan.com` | the same server (only if you turn on TURN for live voice) |
| TXT | `askaasan.com` | SPF from your mail provider |
| TXT / CNAME | DKIM selector(s) | from your mail provider |
| TXT | `_dmarc.askaasan.com` | e.g. `v=DMARC1; p=quarantine; rua=mailto:dmarc@askaasan.com` |

## 2. infra/.env (public address)

Secrets (`POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `LIVEKIT_API_SECRET`) are yours to generate with
`openssl rand -hex 24` / `-hex 32`; never commit them. The rest:

```sh
FRONTEND_URL=https://askaasan.com
WEBAUTHN_ORIGIN=https://askaasan.com
WEBAUTHN_RP_ID=askaasan.com
DJANGO_ALLOWED_HOSTS=askaasan.com,www.askaasan.com,localhost,127.0.0.1,api,web
DJANGO_SECURE_SSL_REDIRECT=true
DJANGO_NUM_PROXIES=1                 # Caddy → nginx. Use 2 behind a cloud load balancer.
DEFAULT_FROM_EMAIL=Aasan <no-reply@askaasan.com>
# The release to run, pulled from GHCR (built by CI on the tag; DEPLOY.md §10 and §11)
TAG=<release tag, e.g. v1.3.0>
AASAN_IMAGE_PREFIX=ghcr.io/<github owner, lowercase>/aasan
# Live voice (docker compose --profile voice)
LIVEKIT_API_KEY=aasan
LIVEKIT_API_SECRET=<openssl rand -hex 32>
LIVEKIT_PUBLIC_URL=wss://askaasan.com/livekit
LIVEKIT_USE_EXTERNAL_IP=true          # or LIVEKIT_NODE_IP=<public IP>
# Optional TURN for school/office networks that block UDP
# LIVEKIT_TURN_ENABLED=true
# LIVEKIT_TURN_DOMAIN=turn.askaasan.com
```

In `api/.env`: run `uv run python manage.py setup_env` (secret keys and the web-push key pair), then set
`WEBPUSH_VAPID_SUBJECT=mailto:support@askaasan.com` and `DJANGO_ADMINS=<your email>`. An AI key (Anthropic,
OpenAI or Gemini) can go here or in **Admin → AI & Voice providers**; web search uses that same key.

The API refuses to start if any of these is unsafe on a public site (http address, local-only hosts, a short
secret key, LiveKit's dev keys) and lists every problem. `tests/test_hardening.py` checks that exactly the values
above start cleanly.

## 3. HTTPS

Install Caddy on the server and use `infra/Caddyfile` (`askaasan.com` → `127.0.0.1:8080`, `www` → redirect).
Open ports **80** and **443**. For live voice also open **UDP 7882** and **TCP 7881**
(plus **5349/tcp** and **3478/udp** with TURN).

```sh
docker login ghcr.io -u <github user>      # once; a token with read:packages if the images are private
docker compose -f infra/docker-compose.yml --profile voice pull
docker compose -f infra/docker-compose.yml --profile voice up -d --no-build
curl -fsS https://askaasan.com/api/health/ready/
curl -sI https://askaasan.com/ | grep -i strict-transport
curl -sI https://www.askaasan.com/ | grep -i location   # → https://askaasan.com/
```

## 4. Outside consoles

| Where | Set to |
|---|---|
| Google sign-in (OAuth client, Web) | Authorised JavaScript origin `https://askaasan.com` |
| Google Calendar sync | Redirect URI `https://askaasan.com/calendar/callback/google` |
| Microsoft Outlook sync | Redirect URI `https://askaasan.com/calendar/callback/microsoft` |
| Organisation SSO (each org's cockpit) | Redirect URI `https://askaasan.com/sso/callback` |
| Razorpay → Webhooks | `https://askaasan.com/api/billing/webhook/` (events in DEPLOY.md §5) |
| Uptime monitor | `https://askaasan.com/api/health/ready/` |
| Browser extension | Defaults to `https://askaasan.com` (`extension/lib.js`); rebuild the zip before uploading it to the store |

## 5. After the first start

1. Sign up, then `docker compose -f infra/docker-compose.yml exec api python manage.py make_admin <you>`.
2. **Admin → System check**: clear every red and amber item (keys, email, legal details, HTTPS/HSTS, monitoring,
   leftover demo accounts). Don't run `seed_demo` on the live server.
3. With the real AI key in place: `docker compose -f infra/docker-compose.yml exec api python manage.py
   check_guardrails` (the safety red-team set, now including web search in role-play and workshops).
4. Nightly backups (`bash infra/backup.sh` from cron, with `BACKUP_AGE_RECIPIENT` set and `BACKUP_COPY_CMD` copying them off the server) and one
   `infra/restore.sh --drill` from the off-server copy (DEPLOY.md §7). Optional: PITR overlay or managed PITR (§7.3).

## 6. What to validate on askaasan.com

**Course page**
- [ ] A course opens on **Map**. Sections sit around the companion and lessons are linked cards. The next lesson
      is the dark card, finished ones show their score, and locked ones are dashed.
- [ ] **Map | Path** switch: Path shows the classic quest path. Reload, and on another device: the choice is kept.
      The same choice is in **Personalize → Learning → Course view**.
- [ ] Timeline and the **Up next / Scores / Skills** panels show in both views. On Path, tapping a section on the
      timeline scrolls to it.
- [ ] Phone width: section chips, one column of cards, no sideways scrolling. Check dark mode and one other theme.
- [ ] Edit my course (reorder, hide), Save for offline, Reset, the before/after test, Checkpoint and Boss fight
      after a finished section.

**Web search in voice** (needs the real AI key; daily limit `MENTOR_WEB_SEARCH_PER_DAY`, default 30)
- [ ] Ask Aasan, by voice: "What's the gold rate in Chennai today?" You get a "searching" moment, a dated answer,
      and source links under the reply.
- [ ] Live Class: a question about today's news searches. Its unprompted remarks don't.
- [ ] Role-play: ask the character something current (e.g. a bus fare). It answers in character, with sources
      under the reply.
- [ ] Workshop: a current-facts question searches. Asking it to find the answer to the exercise online doesn't
      get you the answer.
- [ ] `MENTOR_WEB_SEARCH=false` turns search off everywhere: Aasan says it can't check live information.

**Live voice** (`--profile voice`): a call connects on Wi-Fi and on mobile data, barge-in works, and it ends after
30 minutes.
