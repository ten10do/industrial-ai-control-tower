#!/usr/bin/env python
"""Create or promote the bootstrap administrator.

Phase 6.12 ships authenticated endpoints, which raises an obvious chicken-and-egg
problem: ``POST /auth/register`` deliberately cannot grant ADMIN, so nothing in
the API can produce the first administrator. That is the correct design. A
registration endpoint able to mint its own administrators is a privilege
escalation endpoint wearing a different hat.

The bootstrap therefore happens out of band, through this script, against the
database directly. It is idempotent: running it twice grants the same role twice
and changes nothing the second time.

The password is never taken from the command line. A password in ``argv`` is
visible to every process on the host through the process table and lands in the
shell history file. It is read from ``SECURITY_BOOTSTRAP_PASSWORD`` or, when
that is unset, prompted for without echo.

Usage::

    python scripts/create_admin.py --username admin
    SECURITY_BOOTSTRAP_PASSWORD=... python scripts/create_admin.py --username admin

Exit code 0 on success, 1 on refusal (weak password, missing configuration).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

PASSWORD_ENV = "SECURITY_BOOTSTRAP_PASSWORD"


def _read_password() -> str:
    from_env = os.environ.get(PASSWORD_ENV, "")
    if from_env:
        return from_env
    if not sys.stdin.isatty():
        raise SystemExit(
            f"{PASSWORD_ENV} is not set and stdin is not a terminal, so no password "
            "could be read."
        )
    first = getpass.getpass("Administrator password: ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise SystemExit("Passwords did not match.")
    return first


async def _create(username: str, email: str | None, password: str, role: str) -> dict[str, object]:
    from app.config import get_settings
    from app.infrastructure.database.session import Database
    from app.security.models import UserStatus
    from app.security.passwords import hash_password, validate_password_policy
    from app.security.repository import RoleRepository, UserRepository
    from app.security.service import AuthService

    settings = get_settings()
    database = Database(settings)
    try:
        async with database.sessions() as session:
            users = UserRepository(session)
            existing = await users.get_by_username(username)
            if existing is None:
                validate_password_policy(password, username=username)
                service = AuthService(session)
                user = await service.register(
                    username=username, password=password, email=email, roles=(role,)
                )
                await session.commit()
                return {
                    "status": "created",
                    "user_id": str(user.id),
                    "username": user.username,
                    "roles": [role],
                }
            roles = RoleRepository(session)
            if existing.status != UserStatus.ACTIVE:
                existing.status = UserStatus.ACTIVE.value
            await roles.assign(existing.id, role)
            await session.commit()
            return {
                "status": "promoted",
                "user_id": str(existing.id),
                "username": existing.username,
                "roles": list(await roles.names_for_user(existing.id)),
                "note": "existing user: the password was left unchanged",
            }
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or promote a bootstrap administrator.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", default=None)
    parser.add_argument("--role", default="ADMIN")
    args = parser.parse_args(argv)

    try:
        password = _read_password()
        result = asyncio.run(_create(args.username, args.email, password, args.role))
    except SystemExit as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - the operator needs the real reason
        from app.core.errors import AppError

        if isinstance(exc, AppError):
            print(json.dumps({"status": "refused", "reason": exc.message}), file=sys.stderr)
            return 1
        raise

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
