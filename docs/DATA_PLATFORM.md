# Phase 2 Data Platform

## Storage ownership

PostgreSQL is the system of record. Redis is an expendable cache for latest telemetry; deleting
Redis never deletes telemetry history. Alembic is the only production schema-management path.
Application startup does not call `create_all()`.

The schema separates UUID database primary keys (`id`) from industrial identifiers such as
`MOTOR-001` (`device_id`). Public device routes use the industrial identifier.

## Tables

Phase 2 creates `devices`, `telemetry`, `alarms`, `incidents`, `diagnoses`, `evidence`,
`maintenance_plans`, `approvals`, `work_orders`, `agent_runs`, and `audit_events`. Device,
Telemetry, Alarm, Diagnosis, and AuditEvent have active behavior. The remaining tables are only
minimal persistence foundations for later phases.

Phase 4 migration `20260920_03` enables the pgvector extension and adds
`knowledge_documents`, `knowledge_chunks`, and `retrieval_runs`. Documents store provenance and
content hashes, chunks store filtering/location metadata and `VECTOR(384)` embeddings, and runs
store the complete retrieval/sufficiency audit envelope. The document foreign key cascades chunk
deletion; index ingestion performs changed-document replacement transactionally.

All timestamps are stored as timezone-aware values and normalized to UTC at ingestion. The
telemetry table enforces a device foreign key, non-null measurements, `load_pct` between 0 and
120, and uniqueness of `(device_id, timestamp)`.

## Query patterns and indexes

The primary history query is recent samples for one device, which uses
`(device_id, timestamp)`. Global time-range maintenance uses `timestamp`; operational fault
filtering uses `fault_state`. No per-measurement indexes are created.

History is bounded to 500 records per call and uses an exclusive timestamp cursor. The current
contract permits at most one sample for a device at an instant, so that cursor is unambiguous.

Phase 3 migration `20260917_02` extends `diagnoses` with device and window timestamps, status,
fault type, anomaly score, confidence, severity, JSONB sensor evidence, artifact versions, and
trace ID. `(device_id, created_at)` supports recent-diagnosis queries. Online inference commits a
diagnosis and matching audit event in the same transaction.

## Redis consistency

The key contract is `device:{device_id}:latest`, stored as a hash containing
`timestamp_epoch` and `payload`. A Lua compare-and-set updates it only when the incoming sample
is newer. Database commit happens first. A Redis failure is logged but never rolls back a
committed PostgreSQL sample; latest REST reads fall back to PostgreSQL and opportunistically
rebuild the key.

## Migrations

From `backend/`:

```bash
alembic upgrade head
alembic current
alembic check
```

Container startup runs `alembic upgrade head`, conditionally ingests the versioned knowledge
artifact, and only then starts Uvicorn.

## Retention (design only)

Phase 2 retains raw telemetry indefinitely. A later production phase may introduce a retention
window, downsampling, and archival after measurements and compliance requirements are known.
TimescaleDB and cold storage are intentionally not introduced here.
