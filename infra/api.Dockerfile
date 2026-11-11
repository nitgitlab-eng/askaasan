# Django API image (gunicorn + uvicorn workers; daphne kept as a fallback), also used by the Celery worker/beat and the one-shot migrate job.
# Build context: api/ (see docker-compose.yml); api/.dockerignore keeps .env, the local DB, media and .venv out.
FROM python:3.15-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
# The live voice agent's models (turn detector, VAD), baked in so a call never waits on a download. Before the app
# code, so a code change doesn't download them again (plugins register on import; only registered ones download).
ENV HF_HOME=/app/.cache/huggingface
RUN /app/.venv/bin/python -c "import sys; from livekit.plugins import sarvam, silero; \
from livekit.plugins.turn_detector import multilingual; from livekit.agents import AgentServer, cli; \
sys.argv = ['agent', 'download-files']; cli.run_app(AgentServer())"
COPY . .
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
# Static files are baked in (served by WhiteNoise). The placeholder key only satisfies the production settings check.
RUN DJANGO_SECRET_KEY=collectstatic-build-placeholder-not-used-at-runtime DJANGO_DEBUG=false \
    python manage.py collectstatic --noinput
# Run as an unprivileged user. /app/media is the mediafiles volume; a new volume copies this directory's owner.
# Upgrading a stack whose volume was created as root: docker compose run --rm --user root api chown -R aasan /app/media
# /var/lib/celery holds beat's schedule file (the celerybeat volume copies this owner on first use).
RUN useradd --uid 10001 --no-create-home --home-dir /app aasan && mkdir -p /app/media /var/lib/celery \
    && mkdir -p /app/.cache && chown aasan /app/media /var/lib/celery && chown -R aasan /app/.cache
USER aasan
EXPOSE 8000
# Liveness: any HTTP answer from the API counts (a 301 to HTTPS or a 400 for an unknown host still means it is up).
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 CMD ["python", "-c", "import sys, urllib.request, urllib.error\ntry: urllib.request.urlopen('http://127.0.0.1:8000/api/health/', timeout=4)\nexcept urllib.error.HTTPError: pass\nexcept Exception: sys.exit(1)"]
CMD ["gunicorn", "-c", "config/gunicorn_conf.py", "config.asgi:application"]
