"""Security and governance readiness probes (Phase 6.13-D).

Governance enforcement is only as real as its data layer. A platform whose
HTTP service is alive but whose security migrations are stale, or whose
governance tables are missing, must not report itself ready: the deny paths
in :mod:`app.security.policy_engine` and :mod:`app.security.scope_policy`
would refuse every request (fail-closed), and operators need the readiness
signal to say so before traffic arrives.

Two probes, both fail-closed, both cheap:

* **migrations current** — the row in ``alembic_version`` must equal the head
  revision the repository's ``alembic/versions`` directory actually contains.
  The head is read from the script directory at probe time, never hardcoded,
  so a newly added migration flips readiness until it is applied.
* **governance tables available** — the tables enforcement queries must
  exist. Their absence means the schema was never migrated.

Any error inside a probe degrades to ``"unavailable"``, which the ``/ready``
endpoint folds into ``503 not_ready``. That is the point: an exception during
a readiness check is an answer, and the answer is "not ready".
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: Tables the governance and scope enforcement layers query on request paths.
GOVERNANCE_TABLES: Final[tuple[str, ...]] = (
    "governance_policies",
    "change_records",
    "organizations",
    "plants",
    "areas",
    "user_scopes",
    "device_scopes",
)

_MIGRATIONS_BEHIND = "migrations_behind"
_UNAVAILABLE = "unavailable"
_OK = "ok"


def _alembic_directory() -> Path:
    """Return the repository's ``alembic`` directory (``backend/alembic``)."""

    return Path(__file__).resolve().parents[2] / "alembic"


def expected_migration_head() -> str | None:
    """Return the head revision the version scripts actually describe.

    ``None`` means the script directory could not be read, which the probe
    treats as ``unavailable`` rather than as "current".
    """

    try:
        return ScriptDirectory(str(_alembic_directory())).get_current_head()
    except Exception:
        return None


async def security_readiness(session: AsyncSession) -> str:
    """Return ``ok`` only when migrations are current and tables exist."""

    head = expected_migration_head()
    if head is None:
        return _UNAVAILABLE
    try:
        row = await session.execute(text("SELECT version_num FROM alembic_version"))
        if row.scalar_one() != head:
            return _MIGRATIONS_BEHIND
        for table in GOVERNANCE_TABLES:
            present = await session.execute(
                text("SELECT to_regclass(CAST(:table AS regclass))"), {"table": table}
            )
            if present.scalar_one() is None:
                return _UNAVAILABLE
    except Exception:
        return _UNAVAILABLE
    return _OK


__all__ = ["GOVERNANCE_TABLES", "expected_migration_head", "security_readiness"]
