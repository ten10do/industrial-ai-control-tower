"""Password hashing, the password policy, and access tokens.

The suite is fully in-process: no database, no HTTP, no clock dependency. That
is deliberate, because these are the two primitives everything else rests on and
they should be provable without a running platform.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from app.security import passwords
from app.security.errors import InvalidTokenError, TokenExpiredError, WeakPasswordError
from app.security.passwords import BCRYPT_ROUNDS as SHIPPED_BCRYPT_ROUNDS
from app.security.tokens import (
    ALGORITHM,
    TOKEN_TYPE,
    create_access_token,
    decode_access_token,
)

SECRET = "dummy-unit-test-signing-secret-for-hs256-tests"
OTHER_SECRET = "dummy-other-unit-test-signing-secret-for-hs256"
USER_ID = uuid4()


@pytest.fixture(autouse=True)
def fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower the cost factor so the suite stays fast.

    ``SHIPPED_BCRYPT_ROUNDS`` is bound at import time, before this fixture can
    patch anything, so relaxing the cost here cannot hide a change to the value
    that actually ships.
    """

    monkeypatch.setattr(passwords, "BCRYPT_ROUNDS", 4)
    monkeypatch.setattr(passwords, "_dummy_hash", None)


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #


def test_production_cost_factor_is_twelve() -> None:
    assert SHIPPED_BCRYPT_ROUNDS == 12


def test_a_hash_is_salted_and_never_contains_the_plaintext() -> None:
    password = "dummy-correct-horse-battery-9"
    first = passwords.hash_password(password)
    second = passwords.hash_password(password)

    assert password not in first
    assert first != second, "two hashes of one password must differ (random salt)"
    assert first.startswith("$2b$")


def test_verification_accepts_the_right_password_and_rejects_others() -> None:
    digest = passwords.hash_password("dummy-correct-horse-battery-9")

    assert passwords.verify_password("dummy-correct-horse-battery-9", digest) is True
    assert passwords.verify_password("correct-horse-battery-9", digest) is False
    assert passwords.verify_password("Correct-Horse-Battery-8", digest) is False


def test_a_corrupted_hash_fails_authentication_instead_of_raising() -> None:
    assert passwords.verify_password("anything", "not-a-bcrypt-hash") is False
    assert passwords.verify_password("anything", "") is False


def test_the_dummy_verification_runs_without_an_account() -> None:
    """The timing-equalisation path must not raise on a missing user."""

    passwords.verify_dummy_password("dummy-correct-horse-battery-9")


@pytest.mark.parametrize("password", ["short", "a" * 11])
def test_a_short_password_is_rejected(password: str) -> None:
    with pytest.raises(WeakPasswordError):
        passwords.validate_password_policy(password)


def test_a_password_longer_than_bcrypt_accepts_is_rejected() -> None:
    with pytest.raises(WeakPasswordError):
        passwords.validate_password_policy("a1" * 40)


def test_a_password_equal_to_the_username_is_rejected() -> None:
    with pytest.raises(WeakPasswordError):
        passwords.validate_password_policy("Operator.one", username="operator.one")


def test_an_acceptable_password_passes_the_policy() -> None:
    passwords.validate_password_policy("dummy-correct-horse-battery-9", username="operator.one")


# --------------------------------------------------------------------------- #
# Access tokens
# --------------------------------------------------------------------------- #


def test_a_minted_token_round_trips_with_its_claims() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("OPERATOR",),
        secret=SECRET,
        ttl_seconds=600,
    )

    claims = decode_access_token(issued.token, secret=SECRET)

    assert claims.user_id == USER_ID
    assert claims.username == "operator.one"
    assert claims.roles == ("OPERATOR",)
    assert issued.expires_in_seconds == 600
    assert claims.expires_at > claims.issued_at


def test_the_token_payload_carries_the_contract_fields() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("OPERATOR", "VIEWER"),
        secret=SECRET,
        ttl_seconds=60,
    )

    payload = jwt.decode(issued.token, SECRET, algorithms=[ALGORITHM])

    assert payload["sub"] == str(USER_ID)
    assert payload["user_id"] == str(USER_ID)
    assert payload["username"] == "operator.one"
    assert payload["roles"] == ["OPERATOR", "VIEWER"]
    assert payload["type"] == TOKEN_TYPE
    assert payload["exp"] > payload["iat"]


def test_an_expired_token_is_rejected_with_the_specific_error() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("OPERATOR",),
        secret=SECRET,
        ttl_seconds=60,
        now=datetime.now(UTC) - timedelta(hours=2),
    )

    with pytest.raises(TokenExpiredError):
        decode_access_token(issued.token, secret=SECRET)


def test_a_token_is_rejected_one_second_past_its_expiry() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("OPERATOR",),
        secret=SECRET,
        ttl_seconds=60,
        now=datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC),
    )

    assert decode_access_token(
        issued.token, secret=SECRET, now=datetime(2026, 9, 24, 12, 0, 59, tzinfo=UTC)
    )
    with pytest.raises(TokenExpiredError):
        decode_access_token(
            issued.token, secret=SECRET, now=datetime(2026, 9, 24, 12, 1, 0, tzinfo=UTC)
        )


def test_a_token_signed_with_another_secret_is_rejected() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("OPERATOR",),
        secret=OTHER_SECRET,
        ttl_seconds=600,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(issued.token, secret=SECRET)


def test_a_tampered_token_is_rejected() -> None:
    issued = create_access_token(
        user_id=USER_ID,
        username="operator.one",
        roles=("VIEWER",),
        secret=SECRET,
        ttl_seconds=600,
    )
    header, _, signature = issued.token.split(".")
    claims = jwt.decode(issued.token, SECRET, algorithms=[ALGORITHM])
    claims["roles"] = ["ADMIN"]
    # A payload claiming ADMIN, re-signed with a different key while the original
    # signature is kept: the token must be refused on the signature, not trusted
    # on the claim.
    forged = f"{header}.{jwt.encode(claims, OTHER_SECRET, algorithm=ALGORITHM)}.{signature}"

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_an_unsigned_token_is_rejected() -> None:
    """``alg: none`` must not be accepted as an anonymous administrator."""

    forged = jwt.encode(
        {"sub": str(USER_ID), "roles": ["ADMIN"], "exp": 9999999999, "iat": 1},
        key="",
        algorithm="none",
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_a_token_without_an_expiry_is_rejected() -> None:
    """A missing ``exp`` must not mean "valid forever"."""

    forged = jwt.encode(
        {"sub": str(USER_ID), "iat": 1, "jti": "x"},
        SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_a_token_without_a_subject_is_rejected() -> None:
    forged = jwt.encode(
        {"exp": 9999999999, "iat": 1},
        SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_a_refresh_shaped_token_is_not_accepted_as_an_access_token() -> None:
    forged = jwt.encode(
        {
            "sub": str(USER_ID),
            "type": "refresh",
            "iat": 1,
            "exp": 9999999999,
        },
        SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(forged, secret=SECRET)


def test_a_malformed_token_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_access_token("not.a.jwt", secret=SECRET)
