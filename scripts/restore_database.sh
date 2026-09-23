#!/usr/bin/env bash
# Restore a platform database backup created by backup_database.sh.
#
# The target database is dropped and re-created before the backup is played
# back with psql. This is destructive: the script refuses to run without the
# explicit --yes flag.
#
# Configuration (environment variables, compose defaults):
#   RESTORE_DB_HOST   default localhost
#   RESTORE_DB_PORT   default 5432
#   RESTORE_DB_USER   default postgres (needs CREATEDB privilege)
#   RESTORE_DB_NAME   default industrial_ai_control_tower
#   PSQL_BIN          default psql (override for sandbox/test environments)
#   PGPASSWORD        passed through to psql (never hardcoded here)
#
# Usage: bash scripts/restore_database.sh --yes backup/industrial_ai_20260923.sql

set -euo pipefail

YES_FLAG=""
BACKUP_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --yes) YES_FLAG="yes" ;;
        *) BACKUP_FILE="$1" ;;
    esac
    shift
done

if [ -z "$YES_FLAG" ]; then
    echo "ERROR: restore drops the target database. Re-run with --yes to proceed." >&2
    exit 1
fi

if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: backup file not found: ${BACKUP_FILE:-<none>}" >&2
    exit 1
fi

RESTORE_DB_HOST="${RESTORE_DB_HOST:-localhost}"
RESTORE_DB_PORT="${RESTORE_DB_PORT:-5432}"
RESTORE_DB_USER="${RESTORE_DB_USER:-postgres}"
RESTORE_DB_NAME="${RESTORE_DB_NAME:-industrial_ai_control_tower}"
PSQL_BIN="${PSQL_BIN:-psql}"

if ! command -v "$PSQL_BIN" > /dev/null 2>&1; then
    echo "ERROR: psql binary not found: $PSQL_BIN" >&2
    exit 1
fi

psql_common=(--host="$RESTORE_DB_HOST" --port="$RESTORE_DB_PORT" --username="$RESTORE_DB_USER" --no-password --set=ON_ERROR_STOP=1)

echo "dropping and re-creating database $RESTORE_DB_NAME ..."
PGPASSWORD="${PGPASSWORD:-}" "$PSQL_BIN" "${psql_common[@]}" --dbname=postgres \
    --command="DROP DATABASE IF EXISTS \"$RESTORE_DB_NAME\" WITH (FORCE)"
PGPASSWORD="${PGPASSWORD:-}" "$PSQL_BIN" "${psql_common[@]}" --dbname=postgres \
    --command="CREATE DATABASE \"$RESTORE_DB_NAME\""

echo "restoring from $BACKUP_FILE ..."
PGPASSWORD="${PGPASSWORD:-}" "$PSQL_BIN" "${psql_common[@]}" --dbname="$RESTORE_DB_NAME" \
    --file="$BACKUP_FILE"

echo "restore complete: $RESTORE_DB_NAME"
