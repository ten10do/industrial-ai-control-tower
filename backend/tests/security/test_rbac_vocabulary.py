"""The permission vocabulary, the default grants, and the seeded migration.

No database is needed. The claim being tested is that the vocabulary in code,
the grants in code, and the rows the migration seeds are three views of one
truth, and that the spec's mandated grants are present in it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.security.rbac import (
    ADMIN,
    ALL_PERMISSIONS,
    DASHBOARD_READ,
    DEFAULT_REGISTRATION_ROLE,
    DEFAULT_ROLE_NAMES,
    INCIDENT_ACK,
    INCIDENT_READ,
    INCIDENT_RESOLVE,
    OPERATOR,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSIONS,
    TELEMETRY_READ,
    VIEWER,
    WILDCARD,
    WORKFLOW_START,
    Principal,
    permissions_for_roles,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION_PATH = (
    REPO_ROOT / "backend" / "alembic" / "versions" / "20260924_09_phase6_12_security.py"
)
_spec = importlib.util.spec_from_file_location("phase6_12_migration_under_test", _MIGRATION_PATH)
assert _spec is not None and _spec.loader is not None
migration: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_the_default_roles_are_exactly_the_three_the_spec_names() -> None:
    assert DEFAULT_ROLE_NAMES == (ADMIN, OPERATOR, VIEWER)
    assert tuple(ROLE_PERMISSIONS) == DEFAULT_ROLE_NAMES


def test_admin_holds_the_wildcard_and_user_management() -> None:
    assert WILDCARD in ROLE_PERMISSIONS[ADMIN]
    assert "user.manage" in ROLE_PERMISSIONS[ADMIN]


def test_operator_holds_every_permission_the_spec_lists() -> None:
    granted = set(ROLE_PERMISSIONS[OPERATOR])

    assert {INCIDENT_READ, INCIDENT_ACK, INCIDENT_RESOLVE, WORKFLOW_START} <= granted


def test_viewer_holds_every_permission_the_spec_lists() -> None:
    granted = set(ROLE_PERMISSIONS[VIEWER])

    assert {TELEMETRY_READ, INCIDENT_READ, DASHBOARD_READ} <= granted


def test_viewer_holds_no_write_permission() -> None:
    """The read-only role must be read-only, checked by verb and not by name."""

    write_verbs = {"ack", "resolve", "start", "cancel", "review", "create", "close", "reopen"}
    for permission in ROLE_PERMISSIONS[VIEWER]:
        assert permission != WILDCARD
        assert permission.split(".", 1)[1] not in write_verbs, permission


def test_the_operator_role_is_a_strict_superset_of_the_viewer_role() -> None:
    assert set(ROLE_PERMISSIONS[VIEWER]) < set(ROLE_PERMISSIONS[OPERATOR])


def test_every_permission_is_resource_dot_action() -> None:
    for permission in ALL_PERMISSIONS:
        resource, _, action = permission.partition(".")
        assert resource and action, permission
        assert permission == permission.lower(), permission


def test_the_flat_vocabulary_matches_the_union_of_the_grants() -> None:
    expected = sorted(
        {name for grants in ROLE_PERMISSIONS.values() for name in grants if name != WILDCARD}
    )

    assert list(ALL_PERMISSIONS) == expected


def test_the_registration_default_is_read_only() -> None:
    assert DEFAULT_REGISTRATION_ROLE == VIEWER


def test_every_default_role_has_a_description() -> None:
    assert set(ROLE_DESCRIPTIONS) == set(DEFAULT_ROLE_NAMES)


# --------------------------------------------------------------------------- #
# Migration parity
# --------------------------------------------------------------------------- #


def test_the_migration_seeds_exactly_the_code_vocabulary() -> None:
    """The migration may not import the code table, so it is compared to it."""

    assert {role: set(grants) for role, grants in migration.ROLE_SEED.items()} == {
        role: set(grants) for role, grants in ROLE_PERMISSIONS.items()
    }


def test_the_migration_seeds_the_role_descriptions() -> None:
    assert migration.ROLE_DESCRIPTIONS == ROLE_DESCRIPTIONS


def test_the_migration_revision_chain_is_linear() -> None:
    assert migration.revision == "20260924_09"
    assert migration.down_revision == "20260923_08"


# --------------------------------------------------------------------------- #
# The principal
# --------------------------------------------------------------------------- #


def test_a_wildcard_principal_holds_every_permission() -> None:
    principal = Principal(
        user_id=uuid4(), username="admin", roles=(ADMIN,), permissions=frozenset({WILDCARD})
    )

    assert principal.has_permission(INCIDENT_RESOLVE)
    assert principal.has_permission("a.permission.invented.later")


def test_a_principal_holds_only_its_own_permissions() -> None:
    principal = Principal(
        user_id=uuid4(),
        username="viewer",
        roles=(VIEWER,),
        permissions=frozenset({INCIDENT_READ}),
    )

    assert principal.has_permission(INCIDENT_READ)
    assert not principal.has_permission(INCIDENT_RESOLVE)


def test_a_wildcard_is_not_a_prefix_match() -> None:
    """``*`` grants everything by exact membership, not by globbing."""

    principal = Principal(
        user_id=uuid4(),
        username="odd",
        roles=("ODD",),
        permissions=frozenset({"incident*"}),
    )

    assert not principal.has_permission(INCIDENT_READ)


def test_permissions_for_roles_unions_the_grants() -> None:
    combined = permissions_for_roles([VIEWER, OPERATOR])

    assert combined == frozenset(set(ROLE_PERMISSIONS[VIEWER]) | set(ROLE_PERMISSIONS[OPERATOR]))


def test_permissions_for_roles_is_case_insensitive() -> None:
    assert permissions_for_roles(["operator"]) == permissions_for_roles([OPERATOR])


def test_an_unknown_role_grants_nothing() -> None:
    assert permissions_for_roles(["NOT_A_ROLE"]) == frozenset()


@pytest.mark.parametrize("role", [ADMIN, OPERATOR, VIEWER])
def test_no_role_other_than_admin_holds_the_wildcard(role: str) -> None:
    if role == ADMIN:
        assert WILDCARD in ROLE_PERMISSIONS[role]
    else:
        assert WILDCARD not in ROLE_PERMISSIONS[role]
