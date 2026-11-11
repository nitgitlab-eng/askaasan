# Build the React app, then serve it with nginx. Build context: repo root (see docker-compose.yml).
FROM node:26-alpine AS build
WORKDIR /app
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ .
RUN pnpm build

FROM nginx:1.27-alpine
# The 1.27 tag no longer gets rebuilds, so its Alpine packages (openssl, curl, musl, ...) go stale; take the fixed
# versions from the Alpine repo at build time (CI's Trivy scan fails on HIGH/CRITICAL CVEs that have a fix).
RUN apk upgrade --no-cache
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY infra/nginx/proxy.conf /etc/nginx/snippets/proxy.conf
COPY infra/nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY infra/nginx/media-headers.conf /etc/nginx/snippets/media-headers.conf
COPY infra/nginx/pyodide-headers.conf /etc/nginx/snippets/pyodide-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
# Fail the build on a broken config instead of at container start (the upstream host only resolves inside compose).
RUN sed 's/server api:8000;/server 127.0.0.1:8000;/' /etc/nginx/conf.d/default.conf > /tmp/t.conf \
    && cp /etc/nginx/conf.d/default.conf /tmp/orig.conf && cp /tmp/t.conf /etc/nginx/conf.d/default.conf \
    && nginx -t && cp /tmp/orig.conf /etc/nginx/conf.d/default.conf && rm /tmp/t.conf /tmp/orig.conf
