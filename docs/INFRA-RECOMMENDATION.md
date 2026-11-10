# Hosting recommendation for askaasan.com

For the owner, before launch. It answers: VPS or dedicated server, which provider, what size, and what has to be
done on the host so the hosting items in the gap review are closed. The runbook itself is [DEPLOY.md](DEPLOY.md),
and the askaasan.com values are in [GO-LIVE-askaasan.md](GO-LIVE-askaasan.md).

All prices below are **rough monthly ranges in rupees, written in October 2026**. They change often and depend on
exchange rates, GST and bandwidth. Check each provider's own pricing page before you buy.

## 1. Recommendation

| Decision | Choice |
|---|---|
| Server type | One cloud VM (VPS class), not a dedicated server |
| Region | India: Mumbai, Bengaluru or Hyderabad (whichever your provider has) |
| Size | 4 vCPU / 16 GB RAM, NVMe disk of 160 GB or more |
| Database | Managed Postgres 16 with point-in-time recovery (PITR), same region, if the budget allows. Otherwise the bundled Postgres plus the WAL-G overlay (`infra/docker-compose.pitr.yml`, being added) shipping WAL to object storage |
| Backups | S3-compatible object storage with object lock (write-once) for the nightly dumps, media tarballs and WAL |
| Voice | Starts on the same VM (`--profile voice`). Moves to its own VM when concurrent live calls regularly pass about 12 |
| Later | Dedicated hardware only when you need many cores and the price per core matters more than convenience |

**Why a VPS and not a dedicated server now**

- **Snapshots.** One click (or one API call) gives a whole-disk snapshot before every deploy. Dedicated servers
  usually don't have this.
- **Resize.** Going from 16 GB to 32 GB is a reboot, not a migration to new hardware.
- **Managed add-ons in the same region.** Postgres with PITR, object storage, load balancer, firewall and
  monitoring are a form away. On dedicated hardware you build and run each one yourself.
- **No hardware failures to handle.** A failed disk or power supply on a VM is the provider's problem; the VM
  restarts on other hardware. On a dedicated box you open a ticket and wait, and you need RAID and spare capacity.
- **The box is not the bottleneck.** The October 18 load test (500 concurrent users on an 8 GB laptop Docker VM,
  fake AI) had 0 HTTP errors, p95 under 50 ms and 200/200 WebSockets connected. The real limit is the AI providers'
  rate limits and your monthly spend on them. A bigger server does not change that.

Dedicated wins later on **price per core**: once you run several always-busy app and voice VMs, a 16-core / 64 GB
dedicated server can cost about the same as one mid-size cloud VM. That is a growth-tier decision, not a launch one.

**Why 4 vCPU / 16 GB.** The stack runs Postgres (tuned for a 16 GB host: `shared_buffers` 1 GB,
`effective_cache_size` 4 GB), two Redis instances (512 MB + 256 MB caps), the API (gunicorn with uvicorn workers),
Celery worker and beat, nginx, and, with voice on, LiveKit plus `voice-agent` capped at 4 GB. At peak in the load
test the API used about 1.5 vCPU and 1.2 GB and Postgres about 0.5 vCPU and 200 MB. 16 GB leaves room for the
voice cap, the page cache and a deploy that briefly runs old and new containers. Set `WEB_CONCURRENCY=5` on
4 vCPU (the default formula picks 9, which suits 8 cores). The API image is about 3 GB because of the voice
dependencies, so leave disk for two or three image versions; 160 GB covers images, Docker build cache, a week of
local backups and the database for a long time.

## 2. Provider options

Recommended size (4 vCPU / 16 GB, ~160 GB disk) unless stated. Costs are **approximate ranges**, VM only, before
GST and bandwidth overage. Managed Postgres and storage are extra.

| Provider | Region | VM cost / month (approx.) | Managed Postgres in region? | Object storage? | Notes |
|---|---|---|---|---|---|
| AWS Lightsail | Mumbai (ap-south-1) | ₹7,000–9,000 | Yes (Lightsail databases; no fine-grained PITR control) | Yes (Lightsail buckets, Mumbai) | Fixed price with bandwidth included. Simplest AWS entry. Can move to EC2 later |
| AWS EC2 + RDS | Mumbai; Hyderabad (ap-south-2) | ₹9,000–14,000 (on-demand; less with a 1-year savings plan) | Yes, RDS Postgres with PITR | S3 Mumbai, with Object Lock | Most complete option. Bandwidth out is billed separately and adds up with voice. Most work to set up well |
| DigitalOcean | Bengaluru (BLR1) | ₹8,000–10,000 | Yes, managed Postgres with PITR | Spaces in BLR1 (check object-lock support) | Simple console, predictable pricing, generous included bandwidth |
| Hetzner Cloud | No India region (nearest: Singapore; EU, US) | ₹2,500–4,500 | No | Yes, but not in Asia (check current locations) | Cheapest by far. Costs latency (roughly 40–80 ms more from Tamil Nadu via Singapore, much more via Europe) and keeps learners' data, including minors', outside India |
| E2E Networks (Indian) | Delhi NCR, Mumbai, Chennai (check) | ₹4,000–8,000 | Yes (DBaaS; check PITR) | Yes (EOS, S3-compatible) | Indian company, data stays in India, INR billing with GST invoice. Smaller ecosystem; check snapshot and support terms. Other Indian providers (e.g. Yotta, CtrlS cloud) are worth a quote |
| Dedicated server (OVHcloud, Hetzner, Indian DCs) | OVHcloud has a Mumbai location (check dedicated stock); Hetzner dedicated is EU/US only | ₹6,000–15,000 for 8–16 cores / 64 GB | No (you run it) | Separate purchase | Best price per core. You handle RAID, disk failure, OS, backups and failover; usually no snapshots; setup can take days |

Ruling: **DigitalOcean BLR1 or AWS Mumbai** for most owners (pick by which console you prefer; both have
managed Postgres with PITR in India). **E2E Networks** if INR billing and a strictly Indian provider matter more
than ecosystem. **Hetzner** only if cost dominates and you accept data abroad and the latency.

**Object storage for backups.** Options: AWS S3 Mumbai (Object Lock; data stays in India), DigitalOcean Spaces BLR1,
E2E EOS, or Cloudflare R2 (no egress fees and supports bucket locks, but you can't pin it to India: it offers
location hints such as Asia-Pacific, not an India jurisdiction). For a platform with minors, prefer an India region
unless the cost difference is large. Backup volume at launch is small (a few GB), so the cost is a few hundred
rupees a month on any of them.

## 3. Sizing tiers

| | Pilot (up to ~1k learners) | Growth (up to ~10k learners) | Scale (beyond ~10k) |
|---|---|---|---|
| App | 1 VM, 4 vCPU / 16 GB, everything on it | 2 app VMs (4 vCPU / 8 GB each) behind a cloud load balancer | 3+ app VMs, autoscaling or a container platform |
| Postgres | Managed with PITR, or bundled + WAL-G overlay | Managed, 2 vCPU / 4–8 GB, PITR, standby in the same region | Managed, bigger instance, read replica for reports and exports |
| Redis | Bundled (`redis` + `redis-cache`) | Managed Redis (or a small dedicated VM) for broker, channels and security counters (DB 3) with no eviction; cache separate | Managed, highly available |
| Celery | Worker + beat on the app VM | Workers on every app VM or a small worker VM; **beat on exactly one node** | Dedicated worker pool sized per queue |
| Voice | Same VM, `VOICE_LIVE_MAX_CALLS=12`, `voice-agent` capped at 4 GB | Own voice VM (8–16 GB) running LiveKit + `voice-agent`, TURN on | Several voice-agent VMs; LiveKit sized for media |
| Media | Docker volume on the VM, in the nightly tarball | **Must be on object storage** (S3 media backend, not built yet) | Object storage + CDN |
| Edge | Caddy on the VM | Cloud LB with TLS; `DJANGO_NUM_PROXIES=2`, `set_real_ip_from` in nginx | LB + CDN for static and media |
| Deploy | `docker compose up --build` from a tag, or pull GHCR images | Pull GHCR images, roll one app VM at a time | Same, with WebSocket drain |
| Approx. infra cost | ₹8,000–20,000 / month | ₹35,000–80,000 / month | Depends; review per-core dedicated pricing here |

**Prerequisites before the second app VM** (growth tier). Do these first or the second VM will break things:

1. Media on object storage. Today lesson images, lecture media and generated speech live on the `mediafiles`
   volume of one host, and nginx serves them from there. A second VM would not see them.
2. Celery beat on one node only. Two beats run every periodic job twice (reminders, payment reconcile, retention).
3. Redis and Postgres off the app VM (managed or their own VM), so both app VMs share them.
4. The load balancer forwards real client IPs, so sign-in rate limits and lockouts apply per learner, not per LB.
5. Registry-based deploy (GHCR images on tags, being added), so both VMs run the identical image.

**When to move voice off the app VM.** Each live call is one agent process using 200–400 MB. The new cap
`VOICE_LIVE_MAX_CALLS` (default 12) refuses calls beyond that so a burst can't starve the API. If learners
regularly hit the cap, or the VM's memory sits above 75% during calls, move LiveKit and `voice-agent` to their own
VM and raise the cap there. LiveKit media is UDP-heavy, so check the provider's bandwidth pricing for that VM.

## 4. Go-live checklist on the chosen host

Each row is a hosting item from the gap review and what you do on the provider.

| Item | What to do |
|---|---|
| DNS + HTTPS | A/AAAA for `askaasan.com` and `www` to the VM (and `turn.askaasan.com` if TURN is on); SPF, DKIM, DMARC for mail. Install Caddy with `infra/Caddyfile`. `web` stays on `127.0.0.1:8080`. Check HSTS and the `www` redirect (GO-LIVE §3) |
| Firewall | Provider firewall (cloud firewall / security group), not only `ufw`. Inbound: 80/tcp, 443/tcp; for voice 7882/udp and 7881/tcp; with TURN 5349/tcp and 3478/udp. SSH (22) only from your own IPs, or closed and reached through the provider console / a VPN. Nothing else. Postgres and Redis are never exposed |
| SSH | Keys only: `PasswordAuthentication no`, `PermitRootLogin no` (or `prohibit-password`), a named sudo user per person. Hardware-backed keys (e.g. a YubiKey) for staff if possible |
| Who has access, and logging | Keep a written list of who has SSH and who has the cloud console. Turn on MFA for every console account. Enable `auditd` (or at least keep `journald` / `auth.log` and ship it to Loki) and the provider's console activity log (AWS CloudTrail, DO activity history). Remove access the same day someone leaves |
| Security updates | `unattended-upgrades` for security patches (Ubuntu/Debian), with automatic reboot in a quiet window (e.g. 03:30 IST) or a weekly manual reboot. Update Docker images on each release |
| Disk encryption at rest | Use the provider default (EBS/Lightsail, DO volumes and managed databases encrypt at rest). Confirm it in the console; on a dedicated server you set up LUKS yourself |
| Secrets | Move secrets out of plain `.env` files into Docker secrets or the provider's secret manager, using the `*_FILE` variables the settings now read (e.g. `DJANGO_SECRET_KEY_FILE`). Files readable by root only |
| Snapshots | Daily automatic VM snapshot, kept 7 days, plus a manual one before every deploy |
| Off-host backups | `infra/backup.sh` nightly from cron. It now needs `BACKUP_COPY_CMD` (e.g. `rclone copy` or `aws s3 sync` to the bucket) and `BACKUP_AGE_RECIPIENT` (backups are encrypted with `age` before leaving the host). Keep the `age` private key **off the server** (password manager plus a printed copy). Bucket with object lock / versioning, 30–90 days |
| PITR | Managed Postgres: turn on PITR (7+ days). Bundled Postgres: the WAL-G overlay `infra/docker-compose.pitr.yml` (being added) to the same bucket |
| Restore drill | Monthly, and once before launch: restore last night's dump into a scratch database (DEPLOY §7) and, with PITR, restore to a time 10 minutes ago. Write down how long it took |
| Monitoring | Monitoring overlay `infra/docker-compose.monitoring.yml` (being added): Prometheus, Grafana, Alertmanager, Loki. It scrapes the token-protected `/api/metrics/`; set the token and keep Grafana behind SSH tunnel or auth. Alertmanager emails you on: API not ready, disk > 80%, memory > 85%, backup failure, Celery queue growing, bursts of `account_locked` |
| Error reporting | `SENTRY_DSN` in `api/.env`. The API now refuses to start on a public site without it, unless `SENTRY_OPTIONAL=1` is set on purpose. Use Sentry's EU or US region knowingly (it is a sub-processor) |
| Uptime probe | External monitor (UptimeRobot, Better Stack, or the provider's) on `https://askaasan.com/api/health/ready/` every 1–5 minutes, alerting by email and phone |
| Staging | `infra/docker-compose.staging.yml` (being added) on a small separate VM (2 vCPU / 4 GB is enough) with the fake LLM or a low spend cap. Test every release there first |
| Mail | Real SMTP in production (Amazon SES Mumbai, Zoho, or similar). Stop `mailpit` on the live server; it is for local work only |

## 5. Owner and legal checklist (not code)

These need a person, not a commit.

- [ ] **DPDP counsel review of guardian consent.** The app now emails the guardian a confirm / object link before a
      minor's account is fully active. Ask counsel whether an email link alone counts as "verifiable consent" for
      every case the DPDP Rules cover, and what stronger options you should offer (e.g. DigiLocker-based age or
      identity verification, or a token payment by the guardian). Ask also about retention periods and the
      grievance officer details shown in the app.
- [ ] **DPA template for institutions.** Schools and colleges using organisation accounts will ask for a data
      processing agreement: roles (they are the fiduciary for their students, you the processor), sub-processors,
      breach notice timelines, deletion on exit, data location.
- [ ] **Sub-processor list, kept current.** Hosting provider and region, object storage, email provider, Sentry,
      Razorpay, and every AI vendor: Anthropic, OpenAI, Google, Sarvam, Deepgram. All AI vendors except Sarvam
      process data outside India. Publish the list on the site and update it before adding a vendor.
- [ ] **Zero-retention / no-training terms with each AI vendor.** Confirm in writing (API terms or a signed
      addendum) that learner prompts and audio are not used for training, and get zero or minimal data retention
      where the vendor offers it. Note which ones do not, and route minors' traffic accordingly if counsel says so.
- [ ] **Native Tamil review.** A native Tamil speaker reviews push-notification copy (reminders go to minors and
      their parents) and spot-checks the machine-translated locales before they are switched on.
- [ ] **AI spend.** Set monthly spend caps and alerts with each AI provider and check your rate-limit tier
      (DEPLOY §9). A cap was hit once in October 2026.
- [ ] **Accounts and billing.** Put cloud, DNS, registrar and AI-vendor accounts in the company's name with two
      owners who have MFA, so one lost phone does not lock the business out.

## 6. Deferred items (from the review, not built yet)

None of these block a pilot launch on one VM. The first one blocks the growth tier.

| Item | Why it matters | When |
|---|---|---|
| S3 media backend | Media lives on one VM's volume; a second app VM can't serve it | Before the second app VM |
| Per-learner timezones | Reminders and "today" assume India time; the diaspora gets them at odd hours | Before marketing to the diaspora |
| AI-grade appeal flow | Learners (and guardians) can't contest an AI-assigned grade | Before certificates carry weight with institutions |
| WebSocket drain on deploy | A deploy drops live mentor, workshop and voice sockets; clients reconnect, but mid-answer replies are lost | Before regular daytime deploys; needed for rolling deploys at growth tier |
| Frontend bundle budget | No CI limit on JS size; slow phones on mobile data feel it first | Soon after launch |
| WCAG audit | No formal accessibility audit yet; institutions may require one | Before large institutional contracts |

## 7. Summary for the decision

1. Rent one 4 vCPU / 16 GB VM in an Indian region (DigitalOcean BLR1 or AWS Mumbai; E2E Networks if you want an
   Indian provider). Not a dedicated server yet.
2. Put Postgres on the same provider's managed service with PITR if you can afford it; otherwise use the WAL-G
   overlay. Either way, nightly encrypted backups go to an India-region bucket with object lock.
3. Do section 4 on the host before announcing, and the restore drill once.
4. Run voice on the same VM until calls regularly hit the cap of 12, then give it its own VM.
5. Before the second app VM, build the S3 media backend and move Redis and Postgres off the app VM.
