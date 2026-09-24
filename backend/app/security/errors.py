"""Security error taxonomy.

Every failure here subclasses :class:`app.core.errors.AppError`, so it renders
through the platform's single error envelope (``{"error": {code, message,
trace_id}}``) with no additional exception handler. The ``code`` is the stable
contract the frontend, the runbook, and the audit trail key off; the HTTP status
is the coarse-grained boundary the spec draws:

``401``  no usable identity was presented;
``403``  an identity was presented and it is not allowed to do this;
``429``  too many failed authentication attempts from this origin.
"""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError


class SecurityError(AppError):
    """Base class for every security-boundary failure."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, status_code, details or {})


class AuthenticationRequiredError(SecurityError):
    """No ``Authorization: Bearer`` credential was supplied."""

    def __init__(self, message: str = "Authentication is required.") -> None:
        super().__init__("AUTHENTICATION_REQUIRED", message, 401)


class InvalidTokenError(SecurityError):
    """A credential was supplied and it is not a usable access token."""

    def __init__(self, message: str = "The access token is not valid.") -> None:
        super().__init__("INVALID_TOKEN", message, 401)


class TokenExpiredError(SecurityError):
    """The access token is well formed but past its ``exp``."""

    def __init__(self, message: str = "The access token has expired.") -> None:
        super().__init__("TOKEN_EXPIRED", message, 401)


class InvalidCredentialsError(SecurityError):
    """The username and password pair did not authenticate."""

    def __init__(self, message: str = "Invalid username or password.") -> None:
        super().__init__("INVALID_CREDENTIALS", message, 401)


class AccountDisabledError(SecurityError):
    """The identity exists and is administratively disabled."""

    def __init__(self, message: str = "This account is disabled.") -> None:
        super().__init__("ACCOUNT_DISABLED", message, 401)


class PermissionDeniedError(SecurityError):
    """The identity is valid and lacks the required permission."""

    def __init__(self, permission: str) -> None:
        super().__init__(
            "PERMISSION_DENIED",
            "This identity is not allowed to perform that operation.",
            403,
            {"required_permission": permission},
        )


class LoginRateLimitedError(SecurityError):
    """Too many failed authentication attempts from this origin."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "LOGIN_RATE_LIMITED",
            "Too many failed authentication attempts. Try again later.",
            429,
            {"retry_after_seconds": retry_after_seconds},
        )


class UsernameTakenError(SecurityError):
    """Registration collided with an existing identity."""

    def __init__(self, username: str) -> None:
        super().__init__(
            "USERNAME_TAKEN", "That username is already registered.", 409, {"username": username}
        )


class WeakPasswordError(SecurityError):
    """The supplied password fails the password policy."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            "INVALID_PASSWORD_POLICY", "The password does not meet policy.", 422, {"reason": reason}
        )


class UnknownRoleError(SecurityError):
    """A role name was requested that does not exist in the role table."""

    def __init__(self, role: str) -> None:
        super().__init__("UNKNOWN_ROLE", "That role does not exist.", 422, {"role": role})


class RegistrationDisabledError(SecurityError):
    """Self-service registration is switched off in this deployment."""

    def __init__(self) -> None:
        super().__init__(
            "REGISTRATION_DISABLED", "Registration is disabled in this deployment.", 403
        )


class SecurityNotConfiguredError(SecurityError):
    """The token signing secret is absent, so no token can be trusted."""

    def __init__(self) -> None:
        super().__init__(
            "SECURITY_NOT_CONFIGURED",
            "The token signing secret is not configured.",
            503,
        )
