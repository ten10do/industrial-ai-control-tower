"""FastAPI dependencies for the authentication and authorization boundary.

Two dependencies matter:

:func:`get_principal` turns a bearer token into a :class:`Principal`, or raises
one of the 401 errors. It also publishes the caller into the request-scoped
security context so the existing audit writer can attribute every row written
during the request without any business service changing.

:func:`require_permission` wraps it with an authorization check and raises 403
when the permission is missing. A denial is audited before the exception is
raised, because a rejected attempt is exactly the event an operator needs to
see and the request never reaches a route body that could record it.

A 401 and a 403 are kept rigorously distinct. A missing or unusable credential
is 401; a valid credential without the permission is 403.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.config import get_settings
from app.security.audit import (
    ACTION_PERMISSION_DENIED,
    PERMISSION_RESOURCE,
    STATUS_DENIED,
    record_security_event,
)
from app.security.context import SecurityContext, security_context
from app.security.errors import (
    AccountDisabledError,
    AuthenticationRequiredError,
    InvalidTokenError,
    PermissionDeniedError,
    SecurityNotConfiguredError,
)
from app.security.models import User, UserStatus
from app.security.rate_limit import client_ip
from app.security.rbac import Principal
from app.security.service import IdentityService
from app.security.tokens import decode_access_token

AUTHORIZATION_HEADER = "Authorization"
USER_AGENT_HEADER = "User-Agent"
X_ACTOR_HEADER = "X-Actor"
BEARER_PREFIX = "bearer "

ANONYMOUS_ACTOR = "anonymous"

#: The legacy actor label is metadata, not authority, so it is only bounded in
#: length. Unlike the pre-6.13 ``get_actor`` dependency it is never validated
#: for shape: a forged or malformed label must not fail an authenticated
#: request, it must simply be recorded as the claim it is.
MAX_LEGACY_ACTOR_LENGTH = 200


def legacy_actor_label(request: Request) -> str | None:
    """Return the raw ``X-Actor`` header value, or ``None`` when absent."""

    value = (request.headers.get(X_ACTOR_HEADER) or "").strip()
    if not value:
        return None
    return value[:MAX_LEGACY_ACTOR_LENGTH]


def bearer_token(header: str | None) -> str:
    """Extract the token from an ``Authorization`` header.

    Returns an empty string when the header is absent, and raises when it is
    present but not a bearer credential: a malformed header is a client error
    worth naming, not a silent anonymous request.
    """

    if header is None or not header.strip():
        return ""
    value = header.strip()
    if value.lower().startswith(BEARER_PREFIX):
        return value[len(BEARER_PREFIX) :].strip()
    raise InvalidTokenError("The Authorization header must use the Bearer scheme.")


def _signing_secret() -> str:
    settings = get_settings()
    secret = settings.security_jwt_secret
    if secret is None or not secret.get_secret_value():
        raise SecurityNotConfiguredError()
    return secret.get_secret_value()


def _publish(request: Request, context: SecurityContext) -> None:
    """Make this request's identity visible to the audit writer.

    The context variable is what enriches every audit row written later in the
    same request; ``request.state`` carries the same value for callers that
    already hold the request and prefer explicit access.
    """

    security_context.set(context)
    request.state.security_context = context


async def _authenticate(request: Request, session: AsyncSession) -> Principal:
    """Resolve a bearer credential into a principal, or raise a 401."""

    token = bearer_token(request.headers.get(AUTHORIZATION_HEADER))
    if not token:
        raise AuthenticationRequiredError()
    claims = decode_access_token(token, secret=_signing_secret())
    user = await session.get(User, claims.user_id)
    if user is None:
        raise InvalidTokenError("The access token does not reference a known identity.")
    if user.status != UserStatus.ACTIVE:
        raise AccountDisabledError()
    principal = await IdentityService(session).principal_for(user)
    _publish(
        request,
        SecurityContext(
            actor=user.username,
            actor_user_id=user.id,
            ip_address=client_ip(request),
            user_agent=request.headers.get(USER_AGENT_HEADER),
            legacy_actor=legacy_actor_label(request),
        ),
    )
    return principal


async def get_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    """Return the authenticated caller, or raise a 401."""

    return await _authenticate(request, session)


async def get_optional_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal | None:
    """Return the caller when a credential was supplied, ``None`` otherwise.

    A *present* credential is still validated: an expired or forged token is
    rejected rather than quietly downgraded to anonymous, which is what makes
    this safe to use on a route that only needs to know whether the caller is
    an administrator. An absent credential publishes an anonymous context so
    the route can still audit the source address.
    """

    if not (request.headers.get(AUTHORIZATION_HEADER) or "").strip():
        _publish(
            request,
            SecurityContext(
                actor=ANONYMOUS_ACTOR,
                actor_user_id=None,
                ip_address=client_ip(request),
                user_agent=request.headers.get(USER_AGENT_HEADER),
                legacy_actor=legacy_actor_label(request),
            ),
        )
        return None
    return await _authenticate(request, session)


def get_request_context(request: Request) -> SecurityContext:
    """Publish this request's origin and return it.

    Routes that authenticate *inside* their body rather than through a bearer
    token (login is the only one) still need the source address and client
    description on the audit row they write. This dependency supplies exactly
    that and asserts nothing about identity.
    """

    context = SecurityContext(
        actor=ANONYMOUS_ACTOR,
        actor_user_id=None,
        ip_address=client_ip(request),
        user_agent=request.headers.get(USER_AGENT_HEADER),
    )
    _publish(request, context)
    return context


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    """Build a dependency that enforces one permission on a route."""

    async def dependency(
        request: Request,
        principal: Annotated[Principal, Depends(get_principal)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Principal:
        if principal.has_permission(permission):
            return principal
        await record_security_event(
            session,
            action=ACTION_PERMISSION_DENIED,
            resource=PERMISSION_RESOURCE,
            resource_id=permission,
            status=STATUS_DENIED,
            details={
                "method": request.method,
                "path": request.url.path,
                "roles": list(principal.roles),
            },
            actor=principal.username,
            actor_user_id=principal.user_id,
        )
        raise PermissionDeniedError(permission)

    # The permission is recorded on the dependency itself so the enforcement
    # surface is introspectable. A test walks the route table and fails when a
    # governed route declares no permission, which turns "somebody forgot the
    # dependency" from an invisible omission into a build failure.
    dependency.security_permission = permission  # type: ignore[attr-defined]
    return dependency
