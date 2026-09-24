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


def _load_migration(name: str) -> Any:
    path = REPO_ROOT / "backend" / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Phase 6.12 seeded the original vocabulary; Phase 6.13-A added the alarm,
#: asset-configuration, connectivity, and observability names; Phase 6.13-B
#: added the organization and scope names. Each migration must keep producing
#: the rows it produced on the day it ran, so none may import the code table,
#: and the parity claim is about their *combined* seed.
_phase612 = _load_migration("20260924_09_phase6_12_security.py")
_phase613a = _load_migration("20260924_10_phase6_13_a_actor_migration.py")
_phase613b = _load_migration("20260924_11_phase6_13_b_org_scope.py")
_MIGRATIONS = (_phase612, _phase613a, _phase613b)


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

    write_verbs = {
        "ack",
        "resolve",
        "start",
        "cancel",
        "review",
        "create",
        "close",
        "reopen",
        "clear",
        "update",
        "manage",
        "write",
        "publish",
        "control",
    }
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


def _seed_of(migration: Any) -> dict[str, tuple[str, ...]]:
    """Return a migration's role seed regardless of the phase that wrote it."""

    seed = migration.ROLE_SEED if hasattr(migration, "ROLE_SEED") else migration.GRANTS
    return {role: tuple(grants) for role, grants in seed.items()}


def _seeded_grants() -> dict[str, set[str]]:
    """The union of the grants every seeded migration writes."""

    combined: dict[str, set[str]] = {}
    for migration in _MIGRATIONS:
        for role, grants in _seed_of(migration).items():
            combined.setdefault(role, set()).update(grants)
    return combined


def test_the_migrations_seed_exactly_the_code_vocabulary() -> None:
    """The migrations may not import the code table, so they are compared to it."""

    expected = {role: set(grants) for role, grants in ROLE_PERMISSIONS.items()}
    assert expected == _seeded_grants()


def test_each_migration_is_purely_additive() -> None:
    """A later seed may only add names; it may never re-seed an earlier grant.

    Re-seeding would collide on the ``role_permissions`` primary key, and a
    narrowed re-seed would silently revoke an authority an operator already
    holds. Each migration therefore owns a disjoint slice of the vocabulary.
    """

    for earlier, later in zip(_MIGRATIONS, _MIGRATIONS[1:], strict=False):
        earlier_seed = _seed_of(earlier)
        later_seed = _seed_of(later)
        for role, grants in earlier_seed.items():
            overlap = set(grants) & set(later_seed.get(role, ()))
            assert not overlap, f"{later.revision} re-seeds {sorted(overlap)} for {role}"


def test_the_migration_seeds_the_role_descriptions() -> None:
    assert _phase612.ROLE_DESCRIPTIONS == ROLE_DESCRIPTIONS


def test_the_migration_revision_chain_is_linear() -> None:
    assert _phase612.revision == "20260924_09"
    assert _phase612.down_revision == "20260923_08"
    assert _phase613a.revision == "20260924_10"
    assert _phase613a.down_revision == "20260924_09"
    assert _phase613b.revision == "20260924_11"
    assert _phase613b.down_revision == "20260924_10"


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
