# Deployment Guide

Local, single-host deployment with Docker Compose. This is a
production-oriented prototype foundation — not a Kubernetes or cloud
deployment (those remain out of scope by decision).

## 1. Local Deployment

```bash
cp .env.example .env          # then edit .env with real values (see docs/CONFIGURATION.md)
docker compose up -d --build  # postgres, redis, mosquitto, backend, frontend
```

The backend container entrypoint runs `alembic upgrade head` and the
knowledge ingest before starting uvicorn, so a fresh stack self-migrates.

Every long-running service has a healthcheck and `restart: unless-stopped`,
so an abnormal exit is recovered by the Docker daemon automatically.

Validate the deployment:

```bash
python scripts/deployment_check.py            # JSON report; exit 0 = pass
python scripts/deployment_check.py --require-docker   # treat daemon loss as failure
```

## 2. Environment

All configuration flows through `.env` (categories and validation rules in
[CONFIGURATION.md](CONFIGURATION.md)). Secrets — `POSTGRES_PASSWORD`,
`AGENT_API_KEY`, `MQTT_PASSWORD` — are injected externally and never
committed. A placeholder left unchanged (`change-me-in-dotenv`) fails
`scripts/validate_env.py --mode runtime`.

## 3. Database Migration

Migrations run automatically on container start. To run them manually:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current    # verify
```

`scripts/deployment_check.py` compares the stored `alembic_version` against
the head revision derived from `backend/alembic/versions` and reports
`drift:<version>` when they diverge.

## 4. Backup

```bash
bash scripts/backup_database.sh
# → backup/industrial_ai_YYYYMMDD.sql
```

Configuration: `BACKUP_DB_HOST/PORT/USER/NAME`, `BACKUP_DIR`, and
`PGPASSWORD` (passed through, never hardcoded). Requires `pg_dump` on the
host, or point `PG_DUMP_BIN` at a bundled binary. Schedule it externally
(daily is the prototype default) — see
[DATA_PERSISTENCE.md](DATA_PERSISTENCE.md) for the strategy.

## 5. Restore

```bash
bash scripts/restore_database.sh --yes backup/industrial_ai_20260923.sql
```

Drops and re-creates the target database, then plays the dump back with
`psql --set=ON_ERROR_STOP=1`. Destructive — the script refuses to run
without `--yes`. Restore path and recovery semantics are documented in
[DATA_PERSISTENCE.md](DATA_PERSISTENCE.md).

## 6. Troubleshooting

**database unavailable** — `GET /ready` reports
`checks.database: unavailable` and status 503; the readiness probe itself
retries transient blips three times (1s/2s/4s) before giving up.
Check `docker compose ps postgres`, its logs, and `DATABASE_URL`. The
`/metrics` exposition intentionally keeps serving (with last-known gauge
values) so observability survives a database outage.

**mqtt disconnected** — `/ready` reports `checks.mqtt: degraded`. This does
not flip readiness (the response plane stays ready); the detection plane is
degraded. Check the broker container and `MQTT_HOST`/`MQTT_PORT`. Reconnect
attempts are counted in `mqtt_reconnect_total`.

**redis failure** — `/ready` reports `checks.redis: unavailable` → status
503 (hard dependency). Latest-telemetry reads fail until Redis returns; the
AOF volume (`redis-data`) preserves the newest readings across restarts.

**migration failure** — backend logs show the Alembic error and the
container exits; `restart: unless-stopped` makes it retry. Inspect with
`docker compose logs backend`. Never edit an applied migration; add a new
one. Confirm the stored version with
`scripts/deployment_check.py --database-url <url>` (`drift:<version>`
output means the schema is not at head).

## 7. CI Validation

The `deployment` CI job validates the deployable configuration without
needing a daemon for most steps: compose config, `.env.example` secret scan
(`validate_env.py --mode example`), Dockerfile lint (pinned base images),
and deployment-script smoke tests (including the restore `--yes` refusal).
When the Docker daemon is unavailable the job reports
`DOCKER_DAEMON_UNAVAILABLE` instead of faking a result.
