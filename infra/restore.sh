#!/usr/bin/env bash
# Restore (or drill) a backup written by infra/backup.sh. Run from the repo root.
#
#   bash infra/restore.sh --drill 20261030-021500           # monthly drill: scratch DB, sanity query, drop
#   bash infra/restore.sh 20261030-021500                   # restore into scratch DB aasan_restore_check, keep it
#   bash infra/restore.sh --target-db aasan --force --media-volume 20261030-021500    # real restore (stop writers!)
#
# The backup may be given as a STAMP (looked up in $BACKUP_DIR, default ./backups) or as a path to its db-*.dump.age
# file. The manifest-STAMP.sha256 next to it is checked before anything is decrypted.
#
# Options:
#   --drill            restore into the scratch DB, run a sanity query (count of accounts_user), then drop it
#   --target-db NAME   database to restore into (default aasan_restore_check). Restoring into the live database
#                      ($BACKUP_DB_NAME, default aasan) also needs --force.
#   --force            allow restoring over the live database
#   --media-dir DIR    also unpack the media tarball into DIR on this host (creates DIR/media)
#   --media-volume     also unpack the media tarball into the api container's /app/media (real restore)
#
# Environment:
#   BACKUP_AGE_IDENTITY  age private key file (required for *.age backups). Keep it off this server; copy it in for
#                        the restore and remove it afterwards.
#   BACKUP_DIR, BACKUP_COMPOSE, BACKUP_DB_USER, BACKUP_DB_NAME   as in infra/backup.sh
set -euo pipefail
umask 077

fail() { echo "restore FAILED: $*" >&2; exit 1; }
usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

DRILL=0; FORCE=0; TARGET=""; MEDIA_DIR=""; MEDIA_VOLUME=0; WHICH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --drill) DRILL=1 ;;
    --force) FORCE=1 ;;
    --target-db) TARGET=${2:?--target-db needs a name}; shift ;;
    --media-dir) MEDIA_DIR=${2:?--media-dir needs a directory}; shift ;;
    --media-volume) MEDIA_VOLUME=1 ;;
    -h|--help) usage ;;
    -*) echo "unknown option: $1" >&2; usage ;;
    *) [ -z "$WHICH" ] || usage; WHICH=$1 ;;
  esac
  shift
done
[ -n "$WHICH" ] || usage

DB_USER=${BACKUP_DB_USER:-aasan}
LIVE_DB=${BACKUP_DB_NAME:-aasan}
SCRATCH=aasan_restore_check
read -r -a COMPOSE <<< "${BACKUP_COMPOSE:-docker compose -f infra/docker-compose.yml}"
TARGET=${TARGET:-$SCRATCH}

if [ "$DRILL" = 1 ] && [ "$TARGET" != "$SCRATCH" ]; then fail "--drill always uses the scratch DB $SCRATCH"; fi
if [ "$DRILL" = 1 ] && [ "$MEDIA_VOLUME" = 1 ]; then fail "--drill never writes the live media volume"; fi
case "$TARGET" in *[!A-Za-z0-9_]*) fail "database name must be letters, digits and _ only" ;; esac
if [ "$TARGET" = "$LIVE_DB" ] && [ "$FORCE" != 1 ]; then
  fail "refusing to overwrite the live database '$LIVE_DB' without --force (stop api, worker and beat first)"
fi

# ── Locate the backup files ────────────────────────────────────────────────────────────────────────────────────
if [ -f "$WHICH" ]; then
  DIR=$(cd "$(dirname "$WHICH")" && pwd)
  base=$(basename "$WHICH")
  STAMP=${base#db-}; STAMP=${STAMP%%.*}
else
  DIR=${BACKUP_DIR:-./backups}
  STAMP=$WHICH
fi
case "$STAMP" in [0-9]*-[0-9]*) ;; *) fail "cannot tell the backup stamp from '$WHICH'" ;; esac
MANIFEST="$DIR/manifest-$STAMP.sha256"
[ -f "$MANIFEST" ] || fail "no manifest $MANIFEST"
DB_FILE=$(awk '{print $2}' "$MANIFEST" | grep '^db-' || true)
MEDIA_FILE=$(awk '{print $2}' "$MANIFEST" | grep '^media-' || true)
[ -n "$DB_FILE" ] || fail "manifest lists no database dump"

# ── Verify checksums before decrypting anything ────────────────────────────────────────────────────────────────
if command -v sha256sum >/dev/null 2>&1; then SHA=(sha256sum -c); else SHA=(shasum -a 256 -c); fi
(cd "$DIR" && "${SHA[@]}" "manifest-$STAMP.sha256") || fail "checksum mismatch: the backup is damaged or altered"

# decrypt FILE -> stdout
decrypt() {
  case "$1" in
    *.age) age -d -i "$BACKUP_AGE_IDENTITY" "$1" ;;
    *) cat "$1" ;;
  esac
}

# Check the key before touching any database.
case "$DB_FILE" in *.age)
  [ -n "${BACKUP_AGE_IDENTITY:-}" ] || fail "set BACKUP_AGE_IDENTITY to the age private key file"
  [ -r "$BACKUP_AGE_IDENTITY" ] || fail "cannot read BACKUP_AGE_IDENTITY ($BACKUP_AGE_IDENTITY)"
  command -v age >/dev/null 2>&1 || fail "the 'age' tool is not installed" ;;
esac

psql_db() { "${COMPOSE[@]}" exec -T db psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$1" -Atc "$2"; }

# ── Database ───────────────────────────────────────────────────────────────────────────────────────────────────
if [ "$TARGET" = "$SCRATCH" ]; then
  # Always start the scratch DB fresh so a drill tests the dump, not leftovers.
  psql_db postgres "DROP DATABASE IF EXISTS $SCRATCH WITH (FORCE)" >/dev/null
  psql_db postgres "CREATE DATABASE $SCRATCH" >/dev/null
fi
echo "restore: $DB_FILE -> database $TARGET"
decrypt "$DIR/$DB_FILE" \
  | "${COMPOSE[@]}" exec -T db pg_restore -U "$DB_USER" -d "$TARGET" --clean --if-exists --no-owner --exit-on-error \
  || fail "pg_restore into $TARGET"

# ── Media ──────────────────────────────────────────────────────────────────────────────────────────────────────
if [ -n "$MEDIA_DIR" ] || [ "$MEDIA_VOLUME" = 1 ]; then
  [ -n "$MEDIA_FILE" ] || fail "manifest lists no media archive"
  if [ -n "$MEDIA_DIR" ]; then
    mkdir -p "$MEDIA_DIR"
    decrypt "$DIR/$MEDIA_FILE" | tar -C "$MEDIA_DIR" -xzf - || fail "unpacking media into $MEDIA_DIR"
    echo "restore: media -> $MEDIA_DIR/media"
  fi
  if [ "$MEDIA_VOLUME" = 1 ]; then
    decrypt "$DIR/$MEDIA_FILE" | "${COMPOSE[@]}" run --rm --no-deps --user root -T api tar -C /app -xzf - \
      || fail "unpacking media into the api volume"
    echo "restore: media -> api:/app/media"
  fi
fi

# ── Sanity check (and cleanup for a drill) ─────────────────────────────────────────────────────────────────────
USERS=$(psql_db "$TARGET" "SELECT count(*) FROM accounts_user") || fail "sanity query on $TARGET"
MIGRATIONS=$(psql_db "$TARGET" "SELECT count(*) FROM django_migrations" 2>/dev/null || echo "?")
echo "restore: $TARGET has $USERS users, $MIGRATIONS applied migrations"
if [ "$DRILL" = 1 ]; then
  psql_db postgres "DROP DATABASE $SCRATCH WITH (FORCE)" >/dev/null
  echo "drill ok: backup $STAMP restored, checked and dropped"
else
  echo "restore ok: backup $STAMP is in database $TARGET"
fi
