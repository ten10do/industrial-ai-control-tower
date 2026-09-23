#!/usr/bin/env bash
# Backup the platform PostgreSQL database with pg_dump.
#
# Output: backup/industrial_ai_YYYYMMDD.sql (plain SQL, no owner/privileges,
# so it restores cleanly into a freshly created database).
#
# Configuration (environment variables, compose defaults):
#   BACKUP_DB_HOST   default localhost
#   BACKUP_DB_PORT   default 5432
#   BACKUP_DB_USER   default postgres
#   BACKUP_DB_NAME   default industrial_ai_control_tower
#   BACKUP_DIR       default backup
#   PG_DUMP_BIN      default pg_dump (override for sandbox/test environments,
#                    e.g. the pgserver-bundled binary)
#   PGPASSWORD       passed through to pg_dump (never hardcoded here)
#
# Usage: bash scripts/backup_database.sh

set -euo pipefail

BACKUP_DB_HOST="${BACKUP_DB_HOST:-localhost}"
BACKUP_DB_PORT="${BACKUP_DB_PORT:-5432}"
BACKUP_DB_USER="${BACKUP_DB_USER:-postgres}"
BACKUP_DB_NAME="${BACKUP_DB_NAME:-industrial_ai_control_tower}"
BACKUP_DIR="${BACKUP_DIR:-backup}"
PG_DUMP_BIN="${PG_DUMP_BIN:-pg_dump}"

if ! command -v "$PG_DUMP_BIN" > /dev/null 2>&1; then
    echo "ERROR: pg_dump binary not found: $PG_DUMP_BIN" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d)"
OUT="$BACKUP_DIR/industrial_ai_${STAMP}.sql"

PGPASSWORD="${PGPASSWORD:-}" "$PG_DUMP_BIN" \
    --host="$BACKUP_DB_HOST" \
    --port="$BACKUP_DB_PORT" \
    --username="$BACKUP_DB_USER" \
    --dbname="$BACKUP_DB_NAME" \
    --no-owner \
    --no-privileges \
    --file="$OUT"

if [ ! -s "$OUT" ]; then
    echo "ERROR: backup file is empty: $OUT" >&2
    exit 1
fi

echo "backup written: $OUT"
