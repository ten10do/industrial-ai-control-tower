"""Enterprise governance and compliance API (Phase 6.13-C).

Five capabilities on one router, all additive, none of them a second audit,
device, or asset system:

* **Audit governance** — paged, filtered queries over the one ``audit_events``
  table, through the read methods added to :class:`AuditRepository`. The
  incident timeline and configuration audit keep their own queries untouched.
* **Security events** — the same table, narrowed to the security-boundary
  actions, with an aggregation. The trail is the evidence; this view only
  reads it.
* **Compliance dashboard** — one read-only aggregate over audit rows,
  policies, change records, and identities.
* **Policy management** — CRUD over ``governance_policies`` plus a what-if
  ``evaluate`` endpoint. Enforcement lives in the Policy Engine and runs on
  every governed route via ``require_permission``; this module only authors
  and inspects rules.
* **Change management** — the change-record ledger with its lifecycle state
  machine. The ledger records changes; it never performs them and never
  touches the Workflow / Approval state machines.

Permissions: ``audit.read`` (audit + security events), ``governance.read``
(dashboard, policy register, evaluate), ``governance.manage`` (policy CRUD),
``change.read``, ``change.manage``. Every mutation is attributed to the
authenticated caller through the request-scoped security context, exactly as
on the migrated business surface.

The router is declared without a prefix and mounted under both ``/api/v1``
and ``/api``, matching the platform convention.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.context import trace_id_context
from app.core.errors import AppError
from app.models import User
from app.repositories.audit import (
    MAX_QUERY_LIMIT,
    AuditQueryFilters,
    AuditRepository,
)
from app.security.audit import SECURITY_EVENT_ACTIONS
from app.security.dependencies import require_permission
from app.security.governance_models import (
    CHANGE_TRANSITIONS,
    ChangeRecord,
    ChangeRisk,
    ChangeStatus,
    ChangeType,
    GovernancePolicy,
    PolicyEffect,
)
from app.security.models import UserStatus
from app.security.policy_engine import SUPPORTED_CONDITION_KEYS, evaluate
from app.security.rbac import (
    ALL_PERMISSIONS,
    AUDIT_READ,
    CHANGE_MANAGE,
    CHANGE_READ,
    GOVERNANCE_MANAGE,
    GOVERNANCE_READ,
    Principal,
)

router = APIRouter(tags=["governance"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: Compliance dashboards answer "how are we doing lately", so the window is
#: bounded: a 90-day ceiling keeps the aggregate a dashboard query and stops
#: it becoming a full-table export in disguise.
MAX_DASHBOARD_DAYS = 90

OPEN_CHANGE_STATUSES: tuple[ChangeStatus, ...] = (
    ChangeStatus.DRAFT,
    ChangeStatus.SCHEDULED,
    ChangeStatus.IN_PROGRESS,
)


# --------------------------------------------------------------------------- #
# Contracts
# --------------------------------------------------------------------------- #


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    actor: str
    actor_user_id: UUID | None
    action: str
    resource: str
    resource_id: str | None
    status: str
    ip_address: str | None
    user_agent: str | None
    details: dict[str, Any]
    timestamp: datetime


class AuditPageRead(BaseModel):
    items: list[AuditEventRead]
    total: int
    limit: int
    offset: int


class SecurityEventsRead(BaseModel):
    items: list[AuditEventRead]
    total: int
    limit: int
    offset: int
    summary: dict[str, dict[str, int]]


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    permission: str = Field(min_length=1, max_length=100)
    conditions: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class PolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    permission: str | None = Field(default=None, min_length=1, max_length=100)
    conditions: dict[str, Any] | None = None
    enabled: bool | None = None


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    effect: str
    permission: str
    conditions: dict[str, Any]
    enabled: bool


class PolicyEvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission: str = Field(min_length=1, max_length=100)


class PolicyDecisionRead(BaseModel):
    allowed: bool
    policy_name: str | None
    reason: str | None


class ChangeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    change_type: ChangeType
    risk_level: ChangeRisk
    resource_type: str | None = Field(default=None, max_length=100)
    resource_id: str | None = Field(default=None, max_length=200)


class ChangeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    change_type: ChangeType | None = None
    risk_level: ChangeRisk | None = None
    resource_type: str | None = Field(default=None, max_length=100)
    resource_id: str | None = Field(default=None, max_length=200)


class ChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    change_type: ChangeType
    risk_level: ChangeRisk
    status: ChangeStatus
    resource_type: str | None
    resource_id: str | None
    requested_by_user_id: UUID | None
    requested_by_name: str | None
    scheduled_start: datetime | None
    scheduled_end: datetime | None


class ChangeTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ChangeStatus
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None


class ComplianceDashboardRead(BaseModel):
    window_days: int
    audit: dict[str, Any]
    security_events: dict[str, dict[str, int]]
    policies: dict[str, int]
    changes: dict[str, Any]
    identities: dict[str, int]
    last_audit_at: datetime | None


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

ReadAudit = Annotated[Principal, Depends(require_permission(AUDIT_READ))]
ReadGovernance = Annotated[Principal, Depends(require_permission(GOVERNANCE_READ))]
ManageGovernance = Annotated[Principal, Depends(require_permission(GOVERNANCE_MANAGE))]
ReadChange = Annotated[Principal, Depends(require_permission(CHANGE_READ))]
ManageChange = Annotated[Principal, Depends(require_permission(CHANGE_MANAGE))]


def _audit(
    session: AsyncSession,
    *,
    action: str,
    resource: str,
    resource_id: str,
    principal: Principal,
    details: dict[str, object] | None = None,
) -> None:
    """Record one mutation row attributed to the authenticated caller."""

    AuditRepository(session).add(
        trace_id=trace_id_context.get(),
        action=action,
        resource=resource,
        resource_id=resource_id,
        status="SUCCESS",
        actor=principal.username,
        actor_user_id=principal.user_id,
        details=details or {},
    )


def _validate_conditions(conditions: dict[str, Any]) -> None:
    """Reject condition payloads the engine would treat as inert.

    An unsupported key is a silent no-op at evaluation time, so a typo in a
    governance rule must fail here, at write time, rather than ship a rule
    that enforces nothing.
    """

    for key, value in conditions.items():
        if key not in SUPPORTED_CONDITION_KEYS:
            raise AppError(
                "POLICY_CONDITION_INVALID",
                f"Unsupported policy condition {key!r}; "
                f"supported: {sorted(SUPPORTED_CONDITION_KEYS)}.",
                422,
            )
        if key == "roles":
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            ):
                raise AppError(
                    "POLICY_CONDITION_INVALID",
                    "The 'roles' condition must be a non-empty list of role names.",
                    422,
                )
        elif key == "time_window":
            _validate_time_window(value)
        elif key == "always" and value is not True:
            raise AppError("POLICY_CONDITION_INVALID", "The 'always' condition must be true.", 422)
    if "always" in conditions and len(conditions) > 1:
        raise AppError(
            "POLICY_CONDITION_INVALID",
            "The 'always' condition cannot be combined with other conditions.",
            422,
        )


def _validate_time_window(window: object) -> None:
    if not isinstance(window, dict):
        raise AppError(
            "POLICY_CONDITION_INVALID", "The 'time_window' condition must be an object.", 422
        )
    days = window.get("days")
    if (
        not isinstance(days, list)
        or not days
        or not all(isinstance(day, int) and 1 <= day <= 7 for day in days)
    ):
        raise AppError(
            "POLICY_CONDITION_INVALID",
            "The 'time_window.days' must be a non-empty list of ISO weekdays 1-7 (Monday=1).",
            422,
        )
    for bound in ("start", "end"):
        clock = window.get(bound)
        if not isinstance(clock, str) or len(clock) != 5 or clock[2] != ":":
            raise AppError(
                "POLICY_CONDITION_INVALID",
                f"The 'time_window.{bound}' must be an HH:MM string.",
                422,
            )
        hours, minutes = clock.split(":")
        if not (hours.isdigit() and int(hours) <= 23 and minutes.isdigit() and int(minutes) <= 59):
            raise AppError(
                "POLICY_CONDITION_INVALID",
                f"The 'time_window.{bound}' is not a valid clock time.",
                422,
            )


def _validate_permission_name(permission: str) -> None:
    if permission not in ALL_PERMISSIONS:
        raise AppError(
            "POLICY_PERMISSION_UNKNOWN",
            f"Permission {permission!r} is not in the RBAC vocabulary.",
            422,
        )


async def _require_policy(session: AsyncSession, policy_id: UUID) -> GovernancePolicy:
    row = await session.get(GovernancePolicy, policy_id)
    if row is None:
        raise AppError("POLICY_NOT_FOUND", f"Policy {policy_id} was not found.", 404)
    return row


async def _require_change(session: AsyncSession, change_id: UUID) -> ChangeRecord:
    row = await session.get(ChangeRecord, change_id)
    if row is None:
        raise AppError("CHANGE_NOT_FOUND", f"Change record {change_id} was not found.", 404)
    return row


def _window_query(
    value: str | None,
) -> Any:
    """Parse an ISO 8601 timestamp query parameter; ``None`` stays ``None``."""

    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AppError(
            "VALIDATION_ERROR", f"{value!r} is not a valid ISO 8601 timestamp.", 422
        ) from exc
    if parsed.tzinfo is None:
        raise AppError("VALIDATION_ERROR", "Timestamps must carry a UTC offset.", 422)
    return parsed


# --------------------------------------------------------------------------- #
# Audit governance
# --------------------------------------------------------------------------- #


@router.get("/governance/audit", response_model=AuditPageRead)
async def query_audit(
    session: Session,
    principal: ReadAudit,
    actor: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    resource_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    trace_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_QUERY_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> AuditPageRead:
    """One paged, filtered view of the one audit trail, newest first."""

    filters = AuditQueryFilters(
        actor=actor,
        action=action,
        resource=resource,
        resource_id=resource_id,
        status=status_filter,
        trace_id=trace_id,
        since=_window_query(since),
        until=_window_query(until),
    )
    rows, total = await AuditRepository(session).query(filters, limit=limit, offset=offset)
    return AuditPageRead(
        items=[AuditEventRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/governance/security-events", response_model=SecurityEventsRead)
async def query_security_events(
    session: Session,
    principal: ReadAudit,
    actor: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_QUERY_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SecurityEventsRead:
    """The security-boundary slice of the one audit table.

    Login, logout, registration, and every refused attempt (permission, scope,
    policy) come back together with an aggregation, so an administrator can
    answer "what did the boundary refuse today" without exporting the table.
    """

    filters = AuditQueryFilters(
        actor=actor,
        actions=SECURITY_EVENT_ACTIONS,
        status=status_filter,
        since=_window_query(since),
        until=_window_query(until),
    )
    rows, total = await AuditRepository(session).query(filters, limit=limit, offset=offset)
    summary = await AuditRepository(session).summary(filters)
    return SecurityEventsRead(
        items=[AuditEventRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        summary=summary,
    )


# --------------------------------------------------------------------------- #
# Compliance dashboard
# --------------------------------------------------------------------------- #


@router.get("/governance/compliance/dashboard", response_model=ComplianceDashboardRead)
async def compliance_dashboard(
    session: Session,
    principal: ReadGovernance,
    window_days: int = Query(default=7, ge=1, le=MAX_DASHBOARD_DAYS),
) -> ComplianceDashboardRead:
    """Read-only compliance aggregates over the existing tables.

    Nothing here is cached or copied: every number is computed from
    ``audit_events``, ``governance_policies``, ``change_records``, and
    ``users`` at request time, so the dashboard can never disagree with the
    evidence it summarizes.
    """

    now = datetime.now(UTC)
    since = now - timedelta(days=window_days)
    repository = AuditRepository(session)

    window_filters = AuditQueryFilters(since=since, until=now)
    security_filters = AuditQueryFilters(since=since, until=now, actions=SECURITY_EVENT_ACTIONS)

    by_action = await repository.summary(window_filters)
    audit_by_status: dict[str, int] = {}
    for statuses in by_action.values():
        for status_name, count in statuses.items():
            audit_by_status[status_name] = audit_by_status.get(status_name, 0) + count

    newest = await repository.query(window_filters, limit=1, offset=0)
    last_audit_at = newest[0][0].timestamp if newest[0] else None

    security_summary = await repository.summary(security_filters)

    policy_total = await session.scalar(select(func.count()).select_from(GovernancePolicy))
    policy_enabled = await session.scalar(
        select(func.count()).select_from(GovernancePolicy).where(GovernancePolicy.enabled.is_(True))
    )

    change_by_status: dict[str, int] = {change_status.value: 0 for change_status in ChangeStatus}
    for change_status, count in await session.execute(
        select(ChangeRecord.status, func.count()).group_by(ChangeRecord.status)
    ):
        change_by_status[str(change_status)] = int(count)
    high_risk_open = await session.scalar(
        select(func.count())
        .select_from(ChangeRecord)
        .where(
            ChangeRecord.risk_level == ChangeRisk.HIGH.value,
            ChangeRecord.status.in_([item.value for item in OPEN_CHANGE_STATUSES]),
        )
    )
    change_total = sum(change_by_status.values())

    user_total = await session.scalar(select(func.count()).select_from(User))
    user_active = await session.scalar(
        select(func.count()).select_from(User).where(User.status == UserStatus.ACTIVE.value)
    )

    return ComplianceDashboardRead(
        window_days=window_days,
        audit={"total": sum(audit_by_status.values()), "by_status": audit_by_status},
        security_events=security_summary,
        policies={
            "total": int(policy_total or 0),
            "enabled": int(policy_enabled or 0),
            "disabled": int(policy_total or 0) - int(policy_enabled or 0),
        },
        changes={
            "total": change_total,
            "by_status": change_by_status,
            "high_risk_open": int(high_risk_open or 0),
        },
        identities={"users": int(user_total or 0), "active_users": int(user_active or 0)},
        last_audit_at=last_audit_at,
    )


# --------------------------------------------------------------------------- #
# Policy management
# --------------------------------------------------------------------------- #


@router.get("/governance/policies", response_model=list[PolicyRead])
async def list_policies(session: Session, principal: ReadGovernance) -> list[PolicyRead]:
    rows = list(await session.scalars(select(GovernancePolicy).order_by(GovernancePolicy.name)))
    return [PolicyRead.model_validate(row) for row in rows]


@router.post(
    "/governance/policies",
    response_model=PolicyRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    payload: PolicyCreate,
    session: Session,
    principal: ManageGovernance,
) -> PolicyRead:
    _validate_permission_name(payload.permission)
    _validate_conditions(payload.conditions)
    existing = await session.scalar(
        select(GovernancePolicy).where(GovernancePolicy.name == payload.name)
    )
    if existing is not None:
        raise AppError("POLICY_EXISTS", f"Policy {payload.name!r} already exists.", 409)
    row = GovernancePolicy(
        name=payload.name,
        description=payload.description,
        effect=PolicyEffect.DENY.value,
        permission=payload.permission,
        conditions=payload.conditions,
        enabled=payload.enabled,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        action="GOVERNANCE_POLICY_CREATED",
        resource="policy",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name, "permission": row.permission, "conditions": row.conditions},
    )
    await session.commit()
    return PolicyRead.model_validate(row)


@router.get("/governance/policies/{policy_id}", response_model=PolicyRead)
async def get_policy(policy_id: UUID, session: Session, principal: ReadGovernance) -> PolicyRead:
    return PolicyRead.model_validate(await _require_policy(session, policy_id))


@router.patch("/governance/policies/{policy_id}", response_model=PolicyRead)
async def update_policy(
    policy_id: UUID,
    payload: PolicyUpdate,
    session: Session,
    principal: ManageGovernance,
) -> PolicyRead:
    row = await _require_policy(session, policy_id)
    if payload.name is not None and payload.name != row.name:
        clash = await session.scalar(
            select(GovernancePolicy).where(GovernancePolicy.name == payload.name)
        )
        if clash is not None:
            raise AppError("POLICY_EXISTS", f"Policy {payload.name!r} already exists.", 409)
        row.name = payload.name
    if payload.description is not None:
        row.description = payload.description
    if payload.permission is not None:
        _validate_permission_name(payload.permission)
        row.permission = payload.permission
    if payload.conditions is not None:
        _validate_conditions(payload.conditions)
        row.conditions = payload.conditions
    if payload.enabled is not None:
        row.enabled = payload.enabled
    _audit(
        session,
        action="GOVERNANCE_POLICY_UPDATED",
        resource="policy",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name, "enabled": row.enabled},
    )
    await session.commit()
    return PolicyRead.model_validate(row)


@router.delete("/governance/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: UUID,
    session: Session,
    principal: ManageGovernance,
) -> None:
    row = await _require_policy(session, policy_id)
    _audit(
        session,
        action="GOVERNANCE_POLICY_DELETED",
        resource="policy",
        resource_id=str(row.id),
        principal=principal,
        details={"name": row.name, "permission": row.permission},
    )
    await session.delete(row)
    await session.commit()


@router.post("/governance/policies/evaluate", response_model=PolicyDecisionRead)
async def evaluate_policy(
    payload: PolicyEvaluateRequest,
    session: Session,
    principal: ReadGovernance,
) -> PolicyDecisionRead:
    """Answer "would this caller be refused right now" without changing anything."""

    _validate_permission_name(payload.permission)
    decision = await evaluate(session, principal, payload.permission)
    return PolicyDecisionRead(
        allowed=decision.allowed,
        policy_name=decision.policy_name,
        reason=decision.reason,
    )


# --------------------------------------------------------------------------- #
# Change management
# --------------------------------------------------------------------------- #


@router.get("/governance/changes", response_model=list[ChangeRead])
async def list_changes(
    session: Session,
    principal: ReadChange,
    change_status: Annotated[ChangeStatus | None, Query(alias="status")] = None,
    risk_level: ChangeRisk | None = None,
    change_type: Annotated[ChangeType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChangeRead]:
    statement = select(ChangeRecord).order_by(ChangeRecord.created_at.desc())
    if change_status is not None:
        statement = statement.where(ChangeRecord.status == change_status.value)
    if risk_level is not None:
        statement = statement.where(ChangeRecord.risk_level == risk_level.value)
    if change_type is not None:
        statement = statement.where(ChangeRecord.change_type == change_type.value)
    rows = list(await session.scalars(statement.limit(limit).offset(offset)))
    return [ChangeRead.model_validate(row) for row in rows]


@router.post(
    "/governance/changes",
    response_model=ChangeRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_change(
    payload: ChangeCreate,
    session: Session,
    principal: ManageChange,
) -> ChangeRead:
    row = ChangeRecord(
        title=payload.title,
        description=payload.description,
        change_type=payload.change_type.value,
        risk_level=payload.risk_level.value,
        status=ChangeStatus.DRAFT.value,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        requested_by_user_id=principal.user_id,
        requested_by_name=principal.username,
    )
    session.add(row)
    await session.flush()
    _audit(
        session,
        action="CHANGE_RECORD_CREATED",
        resource="change",
        resource_id=str(row.id),
        principal=principal,
        details={
            "title": row.title,
            "change_type": row.change_type,
            "risk_level": row.risk_level,
        },
    )
    await session.commit()
    return ChangeRead.model_validate(row)


@router.get("/governance/changes/{change_id}", response_model=ChangeRead)
async def get_change(change_id: UUID, session: Session, principal: ReadChange) -> ChangeRead:
    return ChangeRead.model_validate(await _require_change(session, change_id))


@router.patch("/governance/changes/{change_id}", response_model=ChangeRead)
async def update_change(
    change_id: UUID,
    payload: ChangeUpdate,
    session: Session,
    principal: ManageChange,
) -> ChangeRead:
    """Edit the metadata of a draft.

    Once a change is scheduled its record is the plan people may have acted
    on, so the ledger stops accepting edits and the lifecycle becomes the
    only way forward.
    """

    row = await _require_change(session, change_id)
    if ChangeStatus(row.status) is not ChangeStatus.DRAFT:
        raise AppError(
            "CHANGE_NOT_EDITABLE",
            "Only a DRAFT change record can be edited.",
            409,
            {"status": row.status},
        )
    if payload.title is not None:
        row.title = payload.title
    if payload.description is not None:
        row.description = payload.description
    if payload.change_type is not None:
        row.change_type = payload.change_type.value
    if payload.risk_level is not None:
        row.risk_level = payload.risk_level.value
    if payload.resource_type is not None:
        row.resource_type = payload.resource_type
    if payload.resource_id is not None:
        row.resource_id = payload.resource_id
    _audit(
        session,
        action="CHANGE_RECORD_UPDATED",
        resource="change",
        resource_id=str(row.id),
        principal=principal,
    )
    await session.commit()
    return ChangeRead.model_validate(row)


@router.post("/governance/changes/{change_id}/transition", response_model=ChangeRead)
async def transition_change(
    change_id: UUID,
    payload: ChangeTransitionRequest,
    session: Session,
    principal: ManageChange,
) -> ChangeRead:
    """Move a change record along its lifecycle state machine.

    Scheduling (DRAFT → SCHEDULED) requires an execution window, supplied on
    the record or in this request; an end time must be after its start. Any
    transition the state machine does not name is a 409, and a window may only
    be supplied when scheduling.
    """

    row = await _require_change(session, change_id)
    current = ChangeStatus(row.status)
    allowed = CHANGE_TRANSITIONS[current]
    if payload.status not in allowed:
        raise AppError(
            "INVALID_CHANGE_TRANSITION",
            f"A {current.value} change record cannot move to {payload.status.value}.",
            409,
            {"from": current.value, "to": payload.status.value},
        )
    window_supplied = payload.scheduled_start is not None or payload.scheduled_end is not None
    if window_supplied and not (
        current is ChangeStatus.DRAFT and payload.status is ChangeStatus.SCHEDULED
    ):
        raise AppError(
            "INVALID_CHANGE_TRANSITION",
            "An execution window can only be set when scheduling a change.",
            409,
        )
    if payload.scheduled_start is not None:
        row.scheduled_start = payload.scheduled_start
    if payload.scheduled_end is not None:
        row.scheduled_end = payload.scheduled_end
    if payload.status is ChangeStatus.SCHEDULED:
        if row.scheduled_start is None or row.scheduled_end is None:
            raise AppError(
                "CHANGE_WINDOW_REQUIRED",
                "Scheduling a change requires both scheduled_start and scheduled_end.",
                422,
            )
        if row.scheduled_end <= row.scheduled_start:
            raise AppError(
                "CHANGE_WINDOW_INVALID",
                "The change window end must be after its start.",
                422,
            )
    row.status = payload.status.value
    _audit(
        session,
        action="CHANGE_RECORD_TRANSITIONED",
        resource="change",
        resource_id=str(row.id),
        principal=principal,
        details={"from": current.value, "to": payload.status.value},
    )
    await session.commit()
    return ChangeRead.model_validate(row)
