# Deployment

The default local setup (SQLite, no Docker) and the production-shaped
path (Postgres, Docker Compose) share the exact same application code —
nothing in `app/` differs per backend, only `DATABASE_URL`. See
{doc}`../architecture/overview` for why.

## Docker Compose (Postgres path)

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: supply_chain
    ports: ["5432:5432"]
    volumes: ["postgres_data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d supply_chain"]

  app:
    build: .
    env_file: [.env]
    environment:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@postgres:5432/supply_chain
    ports: ["8000:8000"]
    depends_on:
      postgres:
        condition: service_healthy
```

```bash
docker compose up -d
```

The `app` service's `DATABASE_URL` is set directly in
`docker-compose.yml`, overriding whatever `.env` says — this ensures the
containerized app always talks to the containerized Postgres instance by
its Docker network hostname (`postgres`), not `localhost`.

```{warning}
The committed `POSTGRES_PASSWORD: postgres` is a **local development
default only** — replace it (and drop the plaintext env var in favor of a
real secrets mechanism) before running this anywhere reachable outside a
trusted local machine.
```

## `Dockerfile`

```dockerfile
FROM python:3.12-slim AS base
WORKDIR /srv/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini pyproject.toml ./
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
```

Migrations run automatically as part of container startup
(`alembic upgrade head`) before `uvicorn` starts — a fresh container
always brings its own database schema up to date first. Note this image
installs `requirements.txt` (runtime only), **not**
`requirements-dev.txt` — test tooling has no place in a production image.

## Production checklist

- [ ] Replace the Postgres credentials in `docker-compose.yml` with real
  secrets (a `.env`-sourced value, or your orchestrator's secret store —
  never a committed plaintext default).
- [ ] Set `APP_ENV=production` and `LOG_JSON=true` for structured log
  aggregation (see {doc}`../getting-started/configuration`).
- [ ] Tune `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` for expected
  concurrent load — these settings only apply on the Postgres path.
- [ ] Set `PERSIST_FULL_MASTER_DATA_SNAPSHOT=false` if inventory scale
  makes full-snapshot persistence too large per run (see
  {doc}`../features/scalability`, Fix 5).
- [ ] Choose and configure a reasoning engine deliberately for production
  volume — Groq's daily token cap or Gemini's per-minute cap may not fit
  a production request volume; see {doc}`../features/reasoning-engines`.
- [ ] Restrict `CORS_ALLOW_ORIGINS` from the default `["*"]` to actual
  known origins.
- [ ] The REST API surface is minimal today (see
  {doc}`../interfaces/rest-api`) — there is no `/optimize` endpoint yet
  to expose externally; the current production-viable interfaces are the
  CLI script and Streamlit dashboard only.

## What's not built for production yet

- No real task queue for concurrent planning runs — documented, not
  built (see {doc}`../features/scalability`, Fix 6).
- No authentication/authorization anywhere — Streamlit and the API are
  both unauthenticated today.
- No CI deployment step — CI is test-only (see {doc}`ci-cd`); pushing a
  new image and rolling it out is currently a manual `docker compose
  up -d --build` on whatever host runs it.
