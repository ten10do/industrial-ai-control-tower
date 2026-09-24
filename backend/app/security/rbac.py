"""Role-based access control vocabulary, default grants, and the principal.

Two ideas are separated on purpose.

The **permission vocabulary** is code. A permission is a ``resource.action``
string, it is referenced by name at the route that enforces it, and adding a
permission requires an edit here so it cannot appear by accident.

The **role to permission mapping** is data. Phase 6.12 seeds the tables from
``ROLE_PERMISSIONS`` below, but the database is the authorization source of
truth at request time: ``role_permissions`` decides what a token holder may do.
That way the seed is reproducible from code, the runtime is auditable in SQL,
and a future role-management surface needs no new deployment.

``ROLE_PERMISSIONS`` is therefore a *default*, not a constraint. A test asserts
the seeded rows equal this table, so drift between the two is caught rather than
silently tolerated.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

#: Granting ``*`` to a role means "every permission, including ones added
#: later". It is reserved for ADMIN and is deliberately not a wildcard match
#: performed with ``fnmatch``: the check is an exact membership test on this
#: literal, so a permission named ``incident*`` can never be confused with it.
WILDCARD: Final[str] = "*"

TELEMETRY_READ: Final[str] = "telemetry.read"
DASHBOARD_READ: Final[str] = "dashboard.read"

INCIDENT_READ: Final[str] = "incident.read"
INCIDENT_CREATE: Final[str] = "incident.create"
INCIDENT_ACK: Final[str] = "incident.ack"
INCIDENT_INVESTIGATE: Final[str] = "incident.investigate"
INCIDENT_RESOLVE: Final[str] = "incident.resolve"
INCIDENT_CLOSE: Final[str] = "incident.close"
INCIDENT_REOPEN: Final[str] = "incident.reopen"

WORKFLOW_READ: Final[str] = "workflow.read"
WORKFLOW_START: Final[str] = "workflow.start"
WORKFLOW_CANCEL: Final[str] = "workflow.cancel"

APPROVAL_READ: Final[str] = "approval.read"
APPROVAL_REVIEW: Final[str] = "approval.review"

WORKORDER_READ: Final[str] = "workorder.read"

# Phase 6.13-A extends the governed surface to the alarm, asset-configuration,
# connectivity, and observability domains. The naming follows the same
# ``resource.action`` shape; ``alarmrule`` is one word to match ``workorder``.
ALARM_READ: Final[str] = "alarm.read"
ALARM_ACK: Final[str] = "alarm.ack"
ALARM_CLEAR: Final[str] = "alarm.clear"

ALARM_RULE_READ: Final[str] = "alarmrule.read"
ALARM_RULE_CREATE: Final[str] = "alarmrule.create"
ALARM_RULE_UPDATE: Final[str] = "alarmrule.update"

ASSET_READ: Final[str] = "asset.read"
ASSET_MANAGE: Final[str] = "asset.manage"

CONFIG_READ: Final[str] = "config.read"
CONFIG_WRITE: Final[str] = "config.write"
CONFIG_PUBLISH: Final[str] = "config.publish"

CONNECTIVITY_READ: Final[str] = "connectivity.read"
CONNECTIVITY_CONTROL: Final[str] = "connectivity.control"

OBSERVABILITY_READ: Final[str] = "observability.read"

USER_MANAGE: Final[str] = "user.manage"

ADMIN: Final[str] = "ADMIN"
OPERATOR: Final[str] = "OPERATOR"
VIEWER: Final[str] = "VIEWER"

#: Roles seeded by the Phase 6.12 migration, in descending authority.
DEFAULT_ROLE_NAMES: Final[tuple[str, ...]] = (ADMIN, OPERATOR, VIEWER)

#: The role a self-registered user receives. Registration never grants
#: OPERATOR or ADMIN, because a privilege the requester can award themselves is
#: not a privilege.
DEFAULT_REGISTRATION_ROLE: Final[str] = VIEWER

ROLE_PERMISSIONS: Final[dict[str, tuple[str, ...]]] = {
    ADMIN: (WILDCARD, USER_MANAGE),
    OPERATOR: (
        TELEMETRY_READ,
        DASHBOARD_READ,
        INCIDENT_READ,
        INCIDENT_CREATE,
        INCIDENT_ACK,
        INCIDENT_INVESTIGATE,
        INCIDENT_RESOLVE,
        INCIDENT_CLOSE,
        INCIDENT_REOPEN,
        WORKFLOW_READ,
        WORKFLOW_START,
        WORKFLOW_CANCEL,
        APPROVAL_READ,
        APPROVAL_REVIEW,
        WORKORDER_READ,
        ALARM_READ,
        ALARM_ACK,
        ALARM_CLEAR,
        ALARM_RULE_READ,
        ALARM_RULE_CREATE,
        ALARM_RULE_UPDATE,
        ASSET_READ,
        ASSET_MANAGE,
        CONFIG_READ,
        CONFIG_WRITE,
        CONFIG_PUBLISH,
        CONNECTIVITY_READ,
        CONNECTIVITY_CONTROL,
        OBSERVABILITY_READ,
    ),
    VIEWER: (
        TELEMETRY_READ,
        DASHBOARD_READ,
        INCIDENT_READ,
        WORKFLOW_READ,
        APPROVAL_READ,
        WORKORDER_READ,
        ALARM_READ,
        ALARM_RULE_READ,
        ASSET_READ,
        CONFIG_READ,
        CONNECTIVITY_READ,
        OBSERVABILITY_READ,
    ),
}

ROLE_DESCRIPTIONS: Final[dict[str, str]] = {
    ADMIN: "Unrestricted platform authority, including user and role management.",
    OPERATOR: "Runs the incident, workflow, and approval loop for a plant.",
    VIEWER: "Read-only observer of telemetry, incidents, and decisions.",
}

#: Every grantable permission name, excluding the ``*`` literal. Sorted for a
#: stable seed order and a stable test comparison.
ALL_PERMISSIONS: Final[tuple[str, ...]] = tuple(
    sorted({name for grants in ROLE_PERMISSIONS.values() for name in grants if name != WILDCARD})
)


def permissions_for_roles(roles: Iterable[str]) -> frozenset[str]:
    """Return the union of the default grants of ``roles``.

    This is the *seed* derivation used by the migration and by tests. Request
    time authorization reads the database instead, so revoking a grant takes
    effect on the next request rather than on the next deployment.
    """

    granted: set[str] = set()
    for role in roles:
        granted.update(ROLE_PERMISSIONS.get(role.upper(), ()))
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller and the authority it holds right now."""

    user_id: UUID
    username: str
    roles: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_permission(self, permission: str) -> bool:
        """Return whether this principal may perform ``permission``."""

        return WILDCARD in self.permissions or permission in self.permissions
