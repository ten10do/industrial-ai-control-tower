"""Alarm rule registry API.

Rules are data, so creating a threshold, retiring one by disabling it, or
re-scoping one to a device type no longer requires a code change and a redeploy.
The read path and the write path both declare their permission, and since
Phase 6.13-A the write path records the authenticated caller as the actor; a
legacy ``X-Actor`` header is kept only as audit metadata.

Rule authoring cannot reach a device. A rule names a canonical signal, a
comparison, and a threshold; evaluation reads telemetry and writes alarm state.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.incidents.contracts import AlarmRuleCreate, AlarmRuleRead, AlarmRuleUpdate
from app.incidents.service import AlarmRuleService
from app.security.dependencies import require_permission
from app.security.rbac import (
    ALARM_RULE_CREATE,
    ALARM_RULE_READ,
    ALARM_RULE_UPDATE,
    Principal,
)

router = APIRouter(prefix="/alarm-rules", tags=["alarm-rules"])

Session = Annotated[AsyncSession, Depends(get_session)]

#: Every route below declares its own permission; the dependency returns the
#: authenticated principal whose username becomes the audit actor.
ReadRule = Annotated[Principal, Depends(require_permission(ALARM_RULE_READ))]


@router.get("", response_model=list[AlarmRuleRead])
async def list_alarm_rules(
    session: Session,
    principal: ReadRule,
    enabled_only: Annotated[bool, Query()] = False,
) -> list[AlarmRuleRead]:
    """List every rule, or only the enabled ones."""

    rules = await AlarmRuleService(session).list_rules(enabled_only=enabled_only)
    return [AlarmRuleRead.model_validate(rule) for rule in rules]


@router.post("", response_model=AlarmRuleRead, status_code=201)
async def create_alarm_rule(
    payload: AlarmRuleCreate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ALARM_RULE_CREATE))],
) -> AlarmRuleRead:
    """Register one rule.

    A rule may be created disabled. Disabling retires a rule without deleting it,
    so the historical alarms that name it stay explainable.
    """

    rule = await AlarmRuleService(session).create_rule(payload, actor=principal.username)
    return AlarmRuleRead.model_validate(rule)


@router.get("/{rule_id}", response_model=AlarmRuleRead)
async def get_alarm_rule(rule_id: str, session: Session, principal: ReadRule) -> AlarmRuleRead:
    rule = await AlarmRuleService(session).get_rule(rule_id)
    return AlarmRuleRead.model_validate(rule)


@router.patch("/{rule_id}", response_model=AlarmRuleRead)
async def update_alarm_rule(
    rule_id: str,
    payload: AlarmRuleUpdate,
    session: Session,
    principal: Annotated[Principal, Depends(require_permission(ALARM_RULE_UPDATE))],
) -> AlarmRuleRead:
    """Patch one rule. Unset fields are left untouched."""

    rule = await AlarmRuleService(session).update_rule(rule_id, payload, actor=principal.username)
    return AlarmRuleRead.model_validate(rule)
