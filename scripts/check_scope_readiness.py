"""Scope readiness check (Phase 6.13-D deny-by-default migration tool).

Phase 6.13-D removes the migration-period default that granted every identity
without scope bindings the global device reach. Deploying it without
provisioning would lock out every unbound operator, so the correct companion
is an explicit pre-deployment check: this script lists every ACTIVE,
non-admin identity that holds no ``user_scopes`` row, and fails (exit 1) when
any exist. Operators bind them — or accept the loss of reach deliberately —
before the new image rolls out.

Usage::

    DATABASE_URL=postgresql+asyncpg://... python scripts/check_scope_readiness.py

Output is a single JSON object on stdout::

    {"status": "fail", "unbound_users": [{"username": "...", "roles": ["OPERATOR"]}]}

The database is only ever read. No row is created, updated, or deleted, and
no binding is invented on the user's behalf: granting scope is a governance
decision, not a script default.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Role, UserRole
from app.security.models import User, UserStatus
from app.security.org_models import UserScope
from app.security.rbac import ADMIN


async def collect_unbound_users() -> list[dict[str, object]]:
    """Return every ACTIVE non-admin identity without a scope binding."""

    engine = create_async_engine(get_settings().database_url)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            users = list(
                await session.scalars(
                    select(User).where(User.status == UserStatus.ACTIVE).order_by(User.username)
                )
            )
            bound_ids = set(await session.scalars(select(UserScope.user_id).distinct()))
            roles_by_user: dict[object, list[str]] = {}
            for user_id, role_name in await session.execute(
                select(UserRole.user_id, Role.name).join(Role, Role.id == UserRole.role_id)
            ):
                roles_by_user.setdefault(user_id, []).append(role_name)
            return [
                {
                    "username": user.username,
                    "roles": sorted(roles_by_user.get(user.id, [])),
                }
                for user in users
                if user.id not in bound_ids and ADMIN not in roles_by_user.get(user.id, [])
            ]
    finally:
        await engine.dispose()


def main() -> int:
    unbound = asyncio.run(collect_unbound_users())
    if unbound:
        print(json.dumps({"status": "fail", "unbound_users": unbound}, indent=2))
        return 1
    print(json.dumps({"status": "ok", "unbound_users": []}, indent=2))
    return 0


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "DATABASE_URL is not configured; refusing to guess a target.",
                }
            ),
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(main())
