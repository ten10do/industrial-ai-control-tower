"""Authentication API: register, login, and current identity.

Three routes, and each one deliberately does the minimum the spec asks for.

``POST /auth/register``   creates an identity. It is the test-environment
                         provisioning path named in the phase spec: open
                         registration (switchable off), always granting the
                         read-only role unless an authenticated administrator
                         asks for more.
``POST /auth/login``      verifies credentials, returns a signed access token,
                         and writes the audit row either way.
``GET  /auth/me``         returns the caller's identity and effective
                         permissions, which is what lets the operator UI hide
                         an action it would only be refused for. The hiding is
                         cosmetic: the same permission is enforced on the route
                         itself.

The login route never distinguishes "no such user" from "wrong password" in its
response, and it counts failures per source address before it verifies
anything, so a password-guessing run is cut off rather than merely logged.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.config import get_settings
from app.security.audit import (
    ACTION_LOGIN,
    ACTION_REGISTER,
    AUTH_RESOURCE,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    record_security_event,
)
from app.security.context import SecurityContext
from app.security.contracts import (
    IdentityRead,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
)
from app.security.dependencies import (
    get_optional_principal,
    get_principal,
    get_request_context,
)
from app.security.errors import (
    InvalidTokenError,
    RegistrationDisabledError,
    SecurityError,
    SecurityNotConfiguredError,
)
from app.security.models import User
from app.security.rate_limit import LoginRateLimiter, client_ip
from app.security.rbac import USER_MANAGE, Principal
from app.security.service import AuthService, IdentityService
from app.security.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _signing_secret() -> str:
    settings = get_settings()
    secret = settings.security_jwt_secret
    if secret is None or not secret.get_secret_value():
        raise SecurityNotConfiguredError()
    return secret.get_secret_value()


def _rate_limiter(request: Request) -> LoginRateLimiter:
    settings = get_settings()
    redis: Redis | None = getattr(request.app.state, "redis", None)
    return LoginRateLimiter.from_redis(
        redis,
        limit=settings.security_login_rate_limit_attempts,
        window_seconds=settings.security_login_rate_limit_window_seconds,
    )


async def _roles_of(session: AsyncSession, user: User) -> list[str]:
    return list(await IdentityService(session).roles_for(user.id))


@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    payload: RegisterRequest,
    session: Session,
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> UserRead:
    """Create an identity.

    ``roles`` in the payload is honoured only for a caller holding
    ``user.manage``. Anyone else gets :data:`app.security.rbac.VIEWER`, because
    otherwise registration would be a privilege-escalation endpoint.
    """

    settings = get_settings()
    if not settings.security_registration_enabled:
        raise RegistrationDisabledError()

    requested: tuple[str, ...] | None = None
    if payload.roles:
        permitted = principal is not None and principal.has_permission(USER_MANAGE)
        requested = tuple(payload.roles) if permitted else None

    user = await AuthService(session).register(
        username=payload.username,
        password=payload.password,
        email=payload.email,
        roles=requested,
    )
    roles = await _roles_of(session, user)
    await record_security_event(
        session,
        action=ACTION_REGISTER,
        resource=AUTH_RESOURCE,
        resource_id=str(user.id),
        status=STATUS_SUCCESS,
        details={
            "registered_by": principal.username if principal is not None else "self",
            "roles": roles,
            "roles_requested_ignored": bool(payload.roles) and requested is None,
        },
        actor=principal.username if principal is not None else user.username,
        actor_user_id=principal.user_id if principal is not None else user.id,
    )
    return UserRead(
        user_id=user.id,
        username=user.username,
        email=user.email,
        status=user.status,
        roles=roles,
        created_at=user.created_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: Session,
    context: Annotated[SecurityContext, Depends(get_request_context)],
) -> TokenResponse:
    """Verify credentials and return an access token."""

    settings = get_settings()
    secret = _signing_secret()
    limiter = _rate_limiter(request)
    origin = client_ip(request)

    await limiter.check(origin)

    try:
        user = await AuthService(session).authenticate(
            username=payload.username, password=payload.password
        )
    except SecurityError as exc:
        await limiter.register_failure(origin)
        await record_security_event(
            session,
            action=ACTION_LOGIN,
            resource=AUTH_RESOURCE,
            resource_id=payload.username.strip().casefold(),
            status=STATUS_FAILURE,
            details={"reason": exc.code},
            actor=payload.username.strip().casefold(),
            context=context,
        )
        raise

    await limiter.reset(origin)
    roles = tuple(await _roles_of(session, user))
    issued = create_access_token(
        user_id=user.id,
        username=user.username,
        roles=roles,
        secret=secret,
        ttl_seconds=settings.security_access_token_ttl_seconds,
    )
    await record_security_event(
        session,
        action=ACTION_LOGIN,
        resource=AUTH_RESOURCE,
        resource_id=str(user.id),
        status=STATUS_SUCCESS,
        details={"roles": list(roles)},
        actor=user.username,
        actor_user_id=user.id,
        context=context,
    )
    return TokenResponse(
        access_token=issued.token,
        expires_in=issued.expires_in_seconds,
        expires_at=issued.expires_at,
        user_id=user.id,
        username=user.username,
        roles=list(roles),
    )


@router.get("/me", response_model=IdentityRead)
async def me(
    session: Session,
    principal: Annotated[Principal, Depends(get_principal)],
) -> IdentityRead:
    """Return the current identity and the authority it holds right now."""

    user = await session.get(User, principal.user_id)
    if user is None:
        raise InvalidTokenError("The access token does not reference a known identity.")
    return IdentityRead(
        user_id=principal.user_id,
        username=principal.username,
        email=user.email,
        status=user.status,
        roles=list(principal.roles),
        permissions=sorted(principal.permissions),
        created_at=user.created_at,
    )
