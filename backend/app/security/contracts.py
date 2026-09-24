"""Public authentication and identity contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RegisterRequest(BaseModel):
    """Self-service registration payload.

    ``roles`` is accepted for administrative provisioning and is ignored unless
    the caller is already an administrator, so a self-registering user cannot
    award themselves OPERATOR.
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    roles: list[str] | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """The login result: the token plus the identity it represents."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: datetime
    user_id: UUID
    username: str
    roles: list[str]


class IdentityRead(BaseModel):
    """``GET /auth/me``: the current identity and its effective authority."""

    user_id: UUID
    username: str
    email: str | None
    status: str
    roles: list[str]
    permissions: list[str]
    created_at: datetime


class UserRead(BaseModel):
    """A user record as returned by registration."""

    user_id: UUID
    username: str
    email: str | None
    status: str
    roles: list[str]
    created_at: datetime
