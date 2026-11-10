#!/usr/bin/env bash
# First-time settings for a server (or a laptop) that builds Aasan from source.
#
#   bash infra/init-env.sh askaasan.com      # public site behind HTTPS (Caddy)
#   bash infra/init-env.sh localhost         # local trial on http://localhost:8080
#
# Writes infra/.env (database/Redis passwords, LiveKit secret, the public address, TAG) and api/.env (Django secret
# keys and the web-push key pair, via `manage.py setup_env` inside the API image, so the host needs only Docker).
# Never overwrites a file that already exists and never prints a secret. Needs: docker (compose v2) and openssl.
set -euo pipefail

DOMAIN="${1:-}"
[ -n "$DOMAIN" ] || { echo "usage: bash infra/init-env.sh <domain | localhost>" >&2; exit 2; }
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "docker is not installed" >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is not installed" >&2; exit 1; }

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' api/pyproject.toml | head -1)"
TAG="v${VERSION}-local"

set_var() {  # set_var FILE NAME VALUE: replace "NAME=" or append
  local file="$1" name="$2" value="$3"
  if grep -q "^${name}=" "$file"; then
    awk -v n="$name" -v v="$value" 'BEGIN{FS=OFS="="} $1==n {print n "=" v; next} {print}' "$file" >"$file.tmp"
    mv "$file.tmp" "$file"
  else
    printf '%s=%s\n' "$name" "$value" >>"$file"
  fi
}

if [ -e infra/.env ]; then
  echo "infra/.env already exists: left as it is"
else
  cp infra/.env.example infra/.env
  chmod 600 infra/.env
  set_var infra/.env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  set_var infra/.env REDIS_PASSWORD "$(openssl rand -hex 24)"
  set_var infra/.env TAG "$TAG"
  set_var infra/.env AASAN_IMAGE_PREFIX ""
  if [ "$DOMAIN" = "localhost" ]; then
    : # the compose defaults already suit http://localhost:8080 (LiveKit uses its local dev pair)
  else
    set_var infra/.env FRONTEND_URL "https://${DOMAIN}"
    set_var infra/.env WEBAUTHN_ORIGIN "https://${DOMAIN}"
    set_var infra/.env WEBAUTHN_RP_ID "${DOMAIN}"
    set_var infra/.env DJANGO_ALLOWED_HOSTS "${DOMAIN},www.${DOMAIN},localhost,127.0.0.1,api,web"
    set_var infra/.env DJANGO_SECURE_SSL_REDIRECT true
    set_var infra/.env DJANGO_NUM_PROXIES 1
    set_var infra/.env DEFAULT_FROM_EMAIL "Aasan <no-reply@${DOMAIN}>"
    set_var infra/.env LIVEKIT_API_KEY aasan
    set_var infra/.env LIVEKIT_API_SECRET "$(openssl rand -hex 32)"
    set_var infra/.env LIVEKIT_PUBLIC_URL "wss://${DOMAIN}/livekit"
    set_var infra/.env LIVEKIT_USE_EXTERNAL_IP true
  fi
  echo "infra/.env written (TAG=${TAG}, address: ${DOMAIN})"
fi

if [ -e api/.env ]; then
  echo "api/.env already exists: left as it is"
else
  touch api/.env
  chmod 600 api/.env
  echo "building the API image once to generate api/.env (a few minutes the first time)..."
  docker compose -f infra/docker-compose.yml build api
  IMAGE="$(docker compose -f infra/docker-compose.yml config --images api 2>/dev/null | head -1)"
  docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/api:/src" -w /src \
    -e DJANGO_SECRET_KEY=setup-env-placeholder "$IMAGE" python manage.py setup_env
  if [ "$DOMAIN" != "localhost" ]; then
    set_var api/.env WEBPUSH_VAPID_SUBJECT "mailto:support@${DOMAIN}"
  fi
  chmod 600 api/.env
  echo "api/.env written. Add the AI key (or set it later in Admin -> AI & Voice providers) and DJANGO_ADMINS."
fi

echo
echo "Next: docker compose -f infra/docker-compose.yml --profile voice up -d --build"
