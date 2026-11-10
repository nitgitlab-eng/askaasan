#!/usr/bin/env bash
# Nightly backup for the Docker stack: an encrypted Postgres dump + an encrypted tarball of the media volume, a
# sha256 manifest, an off-server copy, and 14 days kept locally. See docs/DEPLOY.md section 7.
#
# Run from the repo root, e.g. cron:
#   15 2 * * *  cd /srv/aasan && bash infra/backup.sh >> /var/log/aasan-backup.log 2>&1
#
# Settings (environment, or BACKUP_* lines in infra/.env; the environment wins):
#   BACKUP_AGE_RECIPIENT    age public key (age1...) or a path to an age recipients file. Both artefacts are encrypted
#                           to it while they stream, so no plaintext dump ever touches the disk.
#   BACKUP_COPY_CMD         shell command that copies $BACKUP_DIR off the server (rclone, aws s3, rsync...). Runs after
#                           every backup with BACKUP_DIR and BACKUP_STAMP exported; a failure fails the backup.
#   BACKUP_REQUIRE_OFFSITE  1 (default): refuse to run unless both settings above are set.
#   BACKUP_ALLOW_LOCAL      1 = dev opt-out: local-only backups, plaintext if no recipient is set. Prints a warning.
#   BACKUP_DIR              where backups are written (default ./backups).
#   BACKUP_KEEP_DAYS        local retention in days (default 14).
#   BACKUP_COMPOSE          compose command (default "docker compose -f infra/docker-compose.yml").
#   BACKUP_DB_USER / BACKUP_DB_NAME   default aasan / aasan.
#
# Output per run (STAMP = YYYYmmdd-HHMMSS):
#   db-STAMP.dump.age  media-STAMP.tgz.age  manifest-STAMP.sha256
# Restore or drill with infra/restore.sh.
# Compose reads infra/.env, so TAG must be set there (compose refuses to run without it).
[ -n "${BASH_VERSION:-}" ] || exec bash "$0" "$@"  # old cron lines call `sh infra/backup.sh`
set -euo pipefail
umask 077

fail() { echo "backup FAILED: $*" >&2; exit 1; }

# BACKUP_* settings from infra/.env, without sourcing the file (it holds other secrets and is not shell syntax).
if [ -f infra/.env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in BACKUP_[A-Z_]*=*) ;; *) continue ;; esac
    key=${line%%=*}
    val=${line#*=}
    case "$val" in \"*\") val=${val#\"}; val=${val%\"} ;; \'*\') val=${val#\'}; val=${val%\'} ;; esac
    if [ -z "${!key:-}" ] && [ -n "$val" ]; then export "$key=$val"; fi
  done < infra/.env
fi

STAMP=$(date +%Y%m%d-%H%M%S)
DEST=${BACKUP_DIR:-./backups}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}
DB_USER=${BACKUP_DB_USER:-aasan}
DB_NAME=${BACKUP_DB_NAME:-aasan}
read -r -a COMPOSE <<< "${BACKUP_COMPOSE:-docker compose -f infra/docker-compose.yml}"
RECIPIENT=${BACKUP_AGE_RECIPIENT:-}
COPY_CMD=${BACKUP_COPY_CMD:-}

# ── Preflight: decide the mode before touching the database ────────────────────────────────────────────────────
if [ "${BACKUP_ALLOW_LOCAL:-0}" = "1" ]; then
  echo "backup WARNING: BACKUP_ALLOW_LOCAL=1 — development mode. These backups are not a disaster-recovery plan" >&2
  [ -n "$RECIPIENT" ] || echo "backup WARNING: BACKUP_AGE_RECIPIENT unset — writing UNENCRYPTED backups" >&2
  [ -n "$COPY_CMD" ] || echo "backup WARNING: BACKUP_COPY_CMD unset — backups stay on this disk only" >&2
elif [ "${BACKUP_REQUIRE_OFFSITE:-1}" = "1" ]; then
  missing=""
  [ -n "$RECIPIENT" ] || missing="$missing BACKUP_AGE_RECIPIENT"
  [ -n "$COPY_CMD" ] || missing="$missing BACKUP_COPY_CMD"
  [ -z "$missing" ] || fail "not set:$missing. Production backups must be encrypted and copied off this server
  (see docs/DEPLOY.md, section 7). For a throwaway dev backup set BACKUP_ALLOW_LOCAL=1."
fi

AGE_ARGS=()
if [ -n "$RECIPIENT" ]; then
  command -v age >/dev/null 2>&1 || fail "the 'age' tool is not installed (apt install age / brew install age)"
  if [ -f "$RECIPIENT" ]; then AGE_ARGS=(-R "$RECIPIENT"); else AGE_ARGS=(-r "$RECIPIENT"); fi
  # Fail now on a malformed key rather than after the dump.
  printf 'x' | age "${AGE_ARGS[@]}" > /dev/null 2>&1 || fail "BACKUP_AGE_RECIPIENT is not a valid age recipient/file"
fi

if command -v sha256sum >/dev/null 2>&1; then SHA=(sha256sum); else SHA=(shasum -a 256); fi

mkdir -p "$DEST"
if [ -n "$RECIPIENT" ]; then SUFFIX=".age"; else SUFFIX=""; fi
DB_FILE="db-$STAMP.dump$SUFFIX"
MEDIA_FILE="media-$STAMP.tgz$SUFFIX"
MANIFEST="manifest-$STAMP.sha256"

# Partial files are removed on any failure, so a half-written backup never looks like a good one.
cleanup() { rm -f "$DEST/.$DB_FILE.part" "$DEST/.$MEDIA_FILE.part" "$DEST/.$MANIFEST.part"; }
trap cleanup EXIT

# encrypt: stdin -> stdout through age when a recipient is set, unchanged otherwise (BACKUP_ALLOW_LOCAL only).
encrypt() { if [ -n "$RECIPIENT" ]; then age "${AGE_ARGS[@]}"; else cat; fi; }

# ── Database: pg_dump streams straight into age ────────────────────────────────────────────────────────────────
"${COMPOSE[@]}" exec -T db pg_dump -U "$DB_USER" -Fc "$DB_NAME" | encrypt > "$DEST/.$DB_FILE.part" \
  || fail "database dump"
# A custom-format dump of even an empty database is several KB; anything tiny means pg_dump wrote nothing.
[ "$(wc -c < "$DEST/.$DB_FILE.part")" -gt 1024 ] || fail "database dump is empty"

# ── Media: a failure here fails the backup too (no silent half-backups); an empty media folder is fine ─────────
"${COMPOSE[@]}" exec -T api sh -c 'mkdir -p /app/media && tar -C /app -czf - media' | encrypt \
  > "$DEST/.$MEDIA_FILE.part" || fail "media archive"

mv "$DEST/.$DB_FILE.part" "$DEST/$DB_FILE"
mv "$DEST/.$MEDIA_FILE.part" "$DEST/$MEDIA_FILE"
(cd "$DEST" && "${SHA[@]}" "$DB_FILE" "$MEDIA_FILE") > "$DEST/.$MANIFEST.part"
mv "$DEST/.$MANIFEST.part" "$DEST/$MANIFEST"

# ── Local retention (the off-server copy keeps its own, longer history) ────────────────────────────────────────
find "$DEST" -maxdepth 1 -type f \( -name 'db-*.dump*' -o -name 'media-*.tgz*' -o -name 'manifest-*.sha256' \) \
  -mtime +"$KEEP_DAYS" -delete

# ── Off-server copy, e.g. 'rclone copy ./backups r2:aasan-backups' or 'rsync -a ./backups/ backup@host:aasan/' ─
if [ -n "$COPY_CMD" ]; then
  export BACKUP_DIR="$DEST" BACKUP_STAMP="$STAMP"
  sh -c "$COPY_CMD" || fail "off-server copy (BACKUP_COPY_CMD exited non-zero)"
fi

echo "backup ok: $DEST/$DB_FILE $DEST/$MEDIA_FILE $DEST/$MANIFEST"
