"""Access tokens: mint, parse, and reject.

The token is a signed (not encrypted) JWT. It carries no authority by itself:
``roles`` in the payload is informational, and every authorization decision
re-reads the caller's grants from the database. That choice costs one indexed
query per authenticated request and buys immediate revocation, which matters
more than the query.

PyJWT is used directly rather than through a wrapper library so the accepted
algorithm list is a literal in this file. ``algorithms=[ALGORITHM]`` is passed
on every decode, which is what makes the ``alg: none`` and HS/RS confusion
attacks fail closed instead of succeeding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt

from app.security.errors import InvalidTokenError, TokenExpiredError

ALGORITHM = "HS256"
TOKEN_TYPE = "access"

#: Claims that must be present for a token to be considered well formed. PyJWT
#: enforces these as a set, so a token minted by another issuer that omits
#: ``exp`` is rejected rather than treated as never expiring.
REQUIRED_CLAIMS = ("exp", "iat", "sub")


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """The validated content of an access token."""

    user_id: UUID
    username: str
    roles: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    token_id: str


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A freshly minted token and the metadata the API reports back."""

    token: str
    issued_at: datetime
    expires_at: datetime

    @property
    def expires_in_seconds(self) -> int:
        return int((self.expires_at - self.issued_at).total_seconds())


def _as_datetime(claim: object) -> datetime:
    if not isinstance(claim, int | float):
        raise InvalidTokenError("The access token carries a malformed timestamp.")
    return datetime.fromtimestamp(float(claim), tz=UTC)


def create_access_token(
    *,
    user_id: UUID,
    username: str,
    roles: tuple[str, ...],
    secret: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> IssuedToken:
    """Mint one signed access token.

    ``now`` exists so expiry can be tested without sleeping: a test mints a
    token in the past and asserts the decode path rejects it.
    """

    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)
    token_id = str(uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "user_id": str(user_id),
        "username": username,
        "roles": list(roles),
        "type": TOKEN_TYPE,
        "jti": token_id,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(payload, secret, algorithm=ALGORITHM)
    return IssuedToken(token=encoded, issued_at=issued_at, expires_at=expires_at)


def decode_access_token(
    token: str, *, secret: str, now: datetime | None = None
) -> AccessTokenClaims:
    """Validate ``token`` and return its claims.

    Expiry is checked explicitly against ``now`` in addition to PyJWT's own
    ``exp`` check, so a caller-supplied clock and the library agree. A token
    that is well formed but expired raises :class:`TokenExpiredError` rather than the
    generic invalid case, because the two have different operator meanings.
    """

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            # PyJWT checks the structure, the signature, and the presence of the
            # required claims. Every *time* claim is evaluated below against the
            # caller's clock instead, so a test or a controlled deployment can
            # reason about expiry without the library reaching for the wall clock
            # behind the caller's back. ``nbf`` keeps its default verification
            # because this platform never issues it and a token that declares
            # itself not yet valid should be refused.
            options={
                "require": list(REQUIRED_CLAIMS),
                "verify_exp": False,
                "verify_iat": False,
            },
        )
    except jwt.InvalidTokenError as exc:  # includes bad signature, bad structure
        raise InvalidTokenError() from exc

    if not isinstance(payload, dict):
        raise InvalidTokenError("The access token payload is malformed.")

    token_type = payload.get("type")
    if token_type != TOKEN_TYPE:
        raise InvalidTokenError("The token is not an access token.")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise InvalidTokenError("The access token has no subject.")
    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise InvalidTokenError("The access token subject is not a user identifier.") from exc

    expires_at = _as_datetime(payload.get("exp"))
    issued_at = _as_datetime(payload.get("iat"))
    reference = now or datetime.now(UTC)
    if reference >= expires_at:
        raise TokenExpiredError()

    username = payload.get("username")
    raw_roles = payload.get("roles")
    token_id = payload.get("jti")
    return AccessTokenClaims(
        user_id=user_id,
        username=username if isinstance(username, str) else "",
        roles=tuple(str(role) for role in raw_roles) if isinstance(raw_roles, list) else (),
        issued_at=issued_at,
        expires_at=expires_at,
        token_id=token_id if isinstance(token_id, str) else "",
    )
