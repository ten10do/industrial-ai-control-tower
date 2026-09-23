"""Alarm rule registry persistence queries.

Annotations are deferred for consistency with the rest of the codebase. Note that
this class deliberately avoids a method named ``list``: a method by that name
rebinds the builtin inside the class body, so a later signature written as
``list[AlarmRule]`` would resolve to the method and fail at import time.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import AlarmRule

#: Deterministic rule order. Rule evaluation returns one breach per rule in the
#: order the rules arrive, so a stable order is what makes the resulting alarm
#: set reproducible for the same readings.
_RULE_ORDER = (AlarmRule.severity.desc(), AlarmRule.id.asc())


class AlarmRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, rule_id: str) -> AlarmRule | None:
        return await self.session.get(AlarmRule, rule_id)

    async def list_rules(self, *, enabled_only: bool = False) -> list[AlarmRule]:
        query = select(AlarmRule)
        if enabled_only:
            query = query.where(AlarmRule.enabled.is_(True))
        rows = await self.session.scalars(query.order_by(*_RULE_ORDER))
        return list(rows)

    async def list_applicable(self, device_type: str | None) -> list[AlarmRule]:
        """Return enabled rules that apply to a device type.

        A rule with no ``device_type`` is global. A rule scoped to a device type
        applies only to that type. Filtering happens in the database so ingestion
        does not read a rule set that grows without bound.
        """

        query = select(AlarmRule).where(AlarmRule.enabled.is_(True))
        if device_type is None:
            query = query.where(AlarmRule.device_type.is_(None))
        else:
            query = query.where(
                (AlarmRule.device_type.is_(None)) | (AlarmRule.device_type == device_type)
            )
        rows = await self.session.scalars(query.order_by(*_RULE_ORDER))
        return list(rows)

    async def create(self, values: dict[str, Any]) -> AlarmRule:
        rule = AlarmRule(**values)
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def apply_update(self, rule: AlarmRule, changes: dict[str, Any]) -> AlarmRule:
        """Assign only the supplied fields, then flush.

        An absent key means "leave this field alone" rather than "set it to
        null", so a partial PATCH cannot silently clear a rule's scope or
        threshold.
        """

        for field, value in changes.items():
            setattr(rule, field, value)
        await self.session.flush()
        return rule
