"""Backup/restore round-trip against the one-shot test PostgreSQL.

Runs the real shell scripts (``scripts/backup_database.sh`` /
``scripts/restore_database.sh``) with real pg_dump/psql binaries when the
pgserver bundle provides them; otherwise the test is skipped — never faked.
"""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

from tests.test_deployment_foundation import run_script


def _pg_client_binaries() -> tuple[Path, Path] | None:
    """Locate pg_dump/psql from the pgserver bundle, if installed."""

    try:
        import pgserver  # noqa: PLC0415
    except ImportError:
        return None
    bin_dir = Path(pgserver.__file__).resolve().parent / "pginstall" / "bin"
    for dump_name, psql_name in (("pg_dump.exe", "psql.exe"), ("pg_dump", "psql")):
        dump, psql = bin_dir / dump_name, bin_dir / psql_name
        if dump.exists() and psql.exists():
            return dump, psql
    return None


@pytest.mark.skipif(
    os.environ.get("ALARM_TEST_DATABASE_URL") is None,
    reason="one-shot PostgreSQL not configured",
)
def test_backup_restore_round_trip_preserves_data(test_database_url: str, tmp_path: Path) -> None:
    """create data -> backup -> drop db -> restore -> verify."""

    binaries = _pg_client_binaries()
    if binaries is None:
        pytest.skip("pg_dump/psql binaries not available (pgserver bundle missing)")

    # Server coordinates from the test database URL.
    parsed = urlparse(test_database_url.replace("postgresql+asyncpg://", "postgresql://"))
    host, port = parsed.hostname, parsed.port or 5432
    roundtrip_db = "backup_roundtrip_test"

    async def seed() -> None:
        admin = await asyncpg.connect(host=host, port=port, user="postgres", database="postgres")
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}" WITH (FORCE)')
            await admin.execute(f'CREATE DATABASE "{roundtrip_db}"')
        finally:
            await admin.close()
        conn = await asyncpg.connect(host=host, port=port, user="postgres", database=roundtrip_db)
        try:
            await conn.execute("CREATE TABLE backup_probe (id int PRIMARY KEY, payload text)")
            await conn.executemany(
                "INSERT INTO backup_probe (id, payload) VALUES ($1, $2)",
                [(1, "alpha"), (2, "beta"), (3, "gamma")],
            )
        finally:
            await conn.close()

    asyncio.run(seed())

    env = {
        **os.environ,
        "BACKUP_DB_HOST": str(host),
        "BACKUP_DB_PORT": str(port),
        "BACKUP_DB_USER": "postgres",
        "BACKUP_DB_NAME": roundtrip_db,
        "BACKUP_DIR": str(tmp_path / "backup"),
        "PG_DUMP_BIN": str(binaries[0]),
        "PGPASSWORD": "",
    }
    backup = run_script("backup_database.sh", env=env)
    assert backup.returncode == 0, backup.stderr
    dump_files = list((tmp_path / "backup").glob("industrial_ai_*.sql"))
    assert len(dump_files) == 1
    dump_file = dump_files[0]
    assert dump_file.stat().st_size > 0

    async def drop() -> None:
        admin = await asyncpg.connect(host=host, port=port, user="postgres", database="postgres")
        try:
            await admin.execute(f'DROP DATABASE "{roundtrip_db}" WITH (FORCE)')
        finally:
            await admin.close()

    asyncio.run(drop())

    restore_env = {
        **os.environ,
        "RESTORE_DB_HOST": str(host),
        "RESTORE_DB_PORT": str(port),
        "RESTORE_DB_USER": "postgres",
        "RESTORE_DB_NAME": roundtrip_db,
        "PSQL_BIN": str(binaries[1]),
        "PGPASSWORD": "",
    }
    restore = run_script("restore_database.sh", "--yes", str(dump_file), env=restore_env)
    assert restore.returncode == 0, restore.stderr

    async def verify() -> list[tuple[int, str]]:
        conn = await asyncpg.connect(host=host, port=port, user="postgres", database=roundtrip_db)
        try:
            rows = await conn.fetch("SELECT id, payload FROM backup_probe ORDER BY id")
        finally:
            await conn.close()
        return [(row["id"], row["payload"]) for row in rows]

    assert asyncio.run(verify()) == [(1, "alpha"), (2, "beta"), (3, "gamma")]

    async def cleanup() -> None:
        admin = await asyncpg.connect(host=host, port=port, user="postgres", database="postgres")
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{roundtrip_db}" WITH (FORCE)')
        finally:
            await admin.close()

    asyncio.run(cleanup())


def test_restore_refuses_without_confirmation() -> None:
    result = run_script(
        "restore_database.sh",
        "/nonexistent.sql",
        env={**os.environ, "PSQL_BIN": "/nonexistent/psql"},
    )
    assert result.returncode == 1
    assert "--yes" in result.stderr
