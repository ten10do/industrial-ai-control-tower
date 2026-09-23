# Data Persistence Strategy

## Persistent Data Map

```
docker volumes
├── postgres-data   → /var/lib/postgresql/data   (system of record)
├── redis-data      → /data                      (latest telemetry cache, AOF)
└── mosquitto-data  → /mosquitto/data            (broker persistence)
```

| Store | What lives there | Losing it means |
|---|---|---|
| PostgreSQL | devices, telemetry history, alarms, incidents, diagnoses, workflows, approvals, work orders, audit events | **Irrecoverable** operational history — this is the system of record |
| Redis | latest-telemetry cache per device (newest reading wins) | Recoverable: the cache re-warms from the next telemetry publish; at-rest diagnosis dedup windows restart |
| Mosquitto | broker session/persistence data | Recoverable: clients reconnect and republish |

PostgreSQL is the only store whose loss is catastrophic; the backup/restore
tooling therefore centres on it.

## Redis Persistence

The compose stack runs Redis with `--appendonly yes` and a named volume
(`redis-data:/data`). The latest-only cache tolerates loss by design —
`LatestTelemetryCache` re-warms from the next accepted reading — but AOF
keeps the newest readings across an intentional restart so the diagnosis
pipeline does not replay stale history.

## MQTT Broker Data

Mosquitto runs with `persistence true` writing to `/mosquitto/data`
(volume `mosquitto-data`). Broker data is transient by nature; no backup is
required.

## Backup Strategy

Only PostgreSQL is backed up.

```bash
bash scripts/backup_database.sh
# → backup/industrial_ai_YYYYMMDD.sql  (plain SQL, --no-owner --no-privileges)
```

- Schedule: run from cron/Task Scheduler at an interval matching the
  acceptable data-loss window (the prototype default: daily). The file name
  is day-scoped, so a same-day re-run replaces that day's snapshot.
- The dump contains everything needed to rebuild the schema and data in a
  fresh database; ownership/privilege statements are stripped so the
  restore works across environments.

## Recovery

```bash
bash scripts/restore_database.sh --yes backup/industrial_ai_20260923.sql
# drops and re-creates the target database, then plays back the dump with psql
```

The `--yes` flag is mandatory — the restore is destructive by definition.
After a restore, the backend's container entrypoint runs
`alembic upgrade head`, which is a no-op when the restored schema is already
at head and a repair path when it is not.

## Recovery Verification

The round-trip is tested continuously, not assumed:
`backend/tests/incidents/test_deployment_roundtrip.py` seeds a probe table,
dumps it with the real script, drops the database, restores from the dump,
and asserts row-for-row equality — the same create → backup → drop →
restore → verify flow an operator would run.
