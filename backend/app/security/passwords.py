"""Password hashing and the password policy.

bcrypt is used directly rather than through an authentication framework: the
framework would add a configuration surface and a dependency graph while the
only thing actually needed is a salted, adaptive hash.

Two bcrypt properties shape the code below.

* bcrypt truncates at 72 bytes, and the 5.x binding raises instead of
  truncating silently. The policy therefore caps a password at 72 UTF-8 bytes,
  which is a real constraint the API states rather than a surprise.
* Verification cost is the defence. A missing user must not short-circuit, or
  response time reveals which usernames exist. :func:`verify_dummy_password`
  burns the same work against a fixed hash so the failure path costs what the
  success path costs.
"""

from __future__ import annotations

import bcrypt

from app.security.errors import WeakPasswordError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_BYTES = 72

#: Cost factor. 12 is the 2026 baseline for interactive logins: roughly a
#: quarter second on server hardware, which is invisible to a human and
#: expensive for an offline attacker.
BCRYPT_ROUNDS = 12

_DUMMY_PASSWORD = b"timing-equalisation-placeholder-value"
_dummy_hash: bytes | None = None


def _encode(password: str) -> bytes:
    return password.encode("utf-8")


def _dummy() -> bytes:
    """Return (and lazily create) the fixed hash used for timing equalisation."""

    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = bcrypt.hashpw(_DUMMY_PASSWORD, bcrypt.gensalt(rounds=BCRYPT_ROUNDS))
    return _dummy_hash


def validate_password_policy(password: str, *, username: str | None = None) -> None:
    """Raise :class:`WeakPasswordError` when ``password`` is not acceptable.

    The policy is intentionally about length and identity, not about character
    classes. Composition rules push people towards ``Password1!`` while length
    rules push them towards passphrases, and only one of those two is worth
    having.
    """

    if len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPasswordError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(_encode(password)) > MAX_PASSWORD_BYTES:
        raise WeakPasswordError(f"password must be at most {MAX_PASSWORD_BYTES} bytes")
    if not password.strip():
        raise WeakPasswordError("password must not be blank")
    if username and password.casefold() == username.casefold():
        raise WeakPasswordError("password must not equal the username")


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash. The plaintext never leaves this function."""

    return bcrypt.hashpw(_encode(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether ``password`` matches ``password_hash``.

    A stored value that is not a valid bcrypt hash returns ``False`` rather than
    raising: a corrupted row must fail authentication, not fail the request with
    a 500 that leaks which row is corrupted.
    """

    try:
        return bcrypt.checkpw(_encode(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def verify_dummy_password(password: str) -> None:
    """Spend the cost of a real verification without any account behind it."""

    verify_password(password, _dummy().decode("ascii"))
