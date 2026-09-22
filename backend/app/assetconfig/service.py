"""Asset hierarchy and versioned device configuration services.

Design boundaries enforced here:

* ``devices`` stays the single device identity source. This module never creates
  device master rows.
* A configuration version is immutable once published. Edits always produce a new
  draft version, so history stays reproducible.
* Publishing and applying are separate facts. Publishing commits the desired
  version to the database, then the gateway is asked to apply it. A failed
  application never rewrites the database into claiming success.
* Validation is side-effect free and never touches the gateway or a device.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assetconfig.apply import ApplyOutcome, DefinitionApplier, UnavailableApplier
from app.assetconfig.audit import (
    APPLY_FAILED,
    APPLY_PENDING,
    APPLY_SUCCEEDED,
    ARCHIVED,
    DRAFT_CREATED,
    DRAFT_DELETED,
    DRAFT_UPDATED,
    PUBLISHED,
    ROLLBACK_DRAFT_CREATED,
    VALIDATED,
    ConfigurationAuditWriter,
    audit_event_to_read,
)
from app.assetconfig.errors import (
    ApplyUnavailableError,
    AssetHierarchyError,
    AssetInUseError,
    AssetNotFoundError,
    ConfigurationConflictError,
    ConfigurationImmutableError,
    ConfigurationNotFoundError,
    ConfigurationStateError,
    ConfigurationValidationError,
    DeviceNotAttachedError,
    DeviceNotFoundError,
)
from app.assetconfig.models import (
    ASSET_PARENT_RULES,
    ApplyStatus,
    AssetNode,
    AssetType,
    ConfigurationSource,
    ConfigurationStatus,
    DeviceConfiguration,
)
from app.assetconfig.repository import (
    AssetRepository,
    ConfigurationAuditRepository,
    ConfigurationRepository,
    DeviceQueryRepository,
)
from app.assetconfig.validation import pydantic_issues, validate_configuration
from app.gateway.models import DeviceDefinition

MUTABLE_STATUSES: frozenset[str] = frozenset(
    {ConfigurationStatus.DRAFT.value, ConfigurationStatus.VALIDATED.value}
)


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_definition(payload: dict[str, Any], device_id: str) -> DeviceDefinition:
    """Parse a payload into the typed definition, or raise a structured error.

    The error classification is shared with the validation pipeline, so a rejected
    payload carries the same codes whether it is refused on write or reported by
    ``/validate``.
    """

    try:
        definition = DeviceDefinition.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationValidationError(
            "configuration payload is not a valid device definition", pydantic_issues(exc)
        ) from exc
    if definition.device_id != device_id:
        raise ConfigurationValidationError(
            "configuration payload device_id does not match the target device",
            [
                {
                    "field": "device_id",
                    "code": "DEVICE_ID_MISMATCH",
                    "message": (
                        f"payload device_id '{definition.device_id}' does not match '{device_id}'"
                    ),
                }
            ],
        )
    return definition


class AssetService:
    """Manage the minimal SITE / LINE hierarchy over the existing devices table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.assets = AssetRepository(session)
        self.devices = DeviceQueryRepository(session)
        self.configs = ConfigurationRepository(session)

    async def create(
        self,
        *,
        name: str,
        asset_type: AssetType,
        parent_id: Any,
        description: str,
        metadata: dict[str, Any],
    ) -> AssetNode:
        parent: AssetNode | None = None
        if parent_id is not None:
            parent = await self.assets.get(parent_id)
            if parent is None:
                raise AssetNotFoundError(f"parent asset '{parent_id}' was not found")
        required_parent = ASSET_PARENT_RULES[asset_type]
        if required_parent is None and parent is not None:
            raise AssetHierarchyError(f"a {asset_type.value} node cannot have a parent")
        if required_parent is not None:
            if parent is None:
                raise AssetHierarchyError(f"a {asset_type.value} node requires a parent")
            if parent.asset_type != required_parent.value:
                raise AssetHierarchyError(
                    f"a {asset_type.value} node must be parented by a "
                    f"{required_parent.value} node, got '{parent.asset_type}'"
                )
        node = AssetNode(
            name=name,
            asset_type=asset_type.value,
            parent_id=parent.id if parent is not None else None,
            description=description,
            node_metadata=metadata,
        )
        await self.assets.create(node)
        await self.session.commit()
        return node

    async def get(self, node_id: Any) -> AssetNode:
        node = await self.assets.get(node_id)
        if node is None:
            raise AssetNotFoundError(f"asset '{node_id}' was not found")
        return node

    async def list_nodes(self) -> list[AssetNode]:
        return await self.assets.list_all()

    async def delete(self, node_id: Any) -> None:
        node = await self.get(node_id)
        if await self.assets.child_count(node.id) > 0:
            raise AssetInUseError(f"asset '{node.name}' still has child nodes; remove them first")
        if await self.assets.device_count(node.id) > 0:
            raise AssetInUseError(
                f"asset '{node.name}' still has devices attached; detach them first"
            )
        await self.assets.delete(node)
        await self.session.commit()

    async def attach_device(self, node_id: Any, device_id: str) -> None:
        node = await self.get(node_id)
        device = await self.devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(f"device '{device_id}' was not found")
        await self.devices.assign_asset(device, node.id)
        await self.session.commit()

    async def detach_device(self, device_id: str) -> None:
        device = await self.devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(f"device '{device_id}' was not found")
        await self.devices.assign_asset(device, None)
        await self.session.commit()

    async def detach_device_from(self, node_id: Any, device_id: str) -> None:
        """Detach a device, but only from the node the request names."""

        node = await self.get(node_id)
        device = await self.devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(f"device '{device_id}' was not found")
        if device.asset_node_id != node.id:
            raise DeviceNotAttachedError(
                f"device '{device_id}' is not attached to asset '{node.name}'"
            )
        await self.devices.assign_asset(device, None)
        await self.session.commit()

    async def device_summaries(self) -> list[dict[str, Any]]:
        """Return every device master row enriched with its configuration state."""

        published = {row.device_id: row for row in await self.configs.list_published()}
        runtime = {row.device_id: row for row in await self.configs.list_runtime_status()}
        summaries: list[dict[str, Any]] = []
        for device in await self.devices.list_all():
            config = published.get(device.device_id)
            status = runtime.get(device.device_id)
            desired = config.version if config is not None else None
            applied = status.applied_version if status is not None else None
            apply_status = (
                ApplyStatus(status.apply_status) if status is not None else ApplyStatus.PENDING
            )
            summaries.append(
                {
                    "device_id": device.device_id,
                    "name": device.name,
                    "device_type": device.device_type,
                    "status": device.status,
                    "asset_node_id": device.asset_node_id,
                    "metadata": device.device_metadata or {},
                    "protocol": config.protocol if config is not None else None,
                    "published_version": desired,
                    "applied_version": applied,
                    "apply_status": apply_status,
                    "in_sync": bool(
                        desired is not None
                        and desired == applied
                        and apply_status is ApplyStatus.APPLIED
                    ),
                }
            )
        return summaries

    async def tree(self) -> dict[str, Any]:
        """Render the hierarchy plus devices that are not attached to any node."""

        nodes = await self.assets.list_all()
        summaries = await self.device_summaries()
        by_node: dict[Any, list[dict[str, Any]]] = {}
        unassigned: list[dict[str, Any]] = []
        for summary in summaries:
            node_id = summary["asset_node_id"]
            if node_id is None:
                unassigned.append(summary)
            else:
                by_node.setdefault(node_id, []).append(summary)
        children: dict[Any, list[AssetNode]] = {}
        roots: list[AssetNode] = []
        for node in nodes:
            if node.parent_id is None:
                roots.append(node)
            else:
                children.setdefault(node.parent_id, []).append(node)

        def build(node: AssetNode) -> dict[str, Any]:
            return {
                "id": node.id,
                "name": node.name,
                "asset_type": node.asset_type,
                "parent_id": node.parent_id,
                "description": node.description,
                "devices": by_node.get(node.id, []),
                "children": [build(child) for child in children.get(node.id, [])],
            }

        return {
            "sites": [build(root) for root in roots],
            "unassigned_devices": unassigned,
        }


class ConfigurationService:
    """Manage the draft, validate, publish, and apply lifecycle of configurations."""

    def __init__(self, session: AsyncSession, applier: DefinitionApplier | None = None) -> None:
        self.session = session
        self.applier: DefinitionApplier = applier or UnavailableApplier()
        self.configs = ConfigurationRepository(session)
        self.devices = DeviceQueryRepository(session)
        self.audit = ConfigurationAuditWriter(session)
        self.audit_reader = ConfigurationAuditRepository(session)

    async def _require_device(self, device_id: str) -> Any:
        device = await self.devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(f"device '{device_id}' was not found")
        return device

    async def list_configurations(self, device_id: str) -> list[DeviceConfiguration]:
        await self._require_device(device_id)
        return await self.configs.list_for_device(device_id)

    async def get_configuration(self, device_id: str, version: int) -> DeviceConfiguration:
        await self._require_device(device_id)
        row = await self.configs.get(device_id, version)
        if row is None:
            raise ConfigurationNotFoundError(
                f"device '{device_id}' has no configuration version {version}"
            )
        return row

    async def create_draft(
        self, device_id: str, payload: dict[str, Any], actor: str
    ) -> DeviceConfiguration:
        await self._require_device(device_id)
        definition = _parse_definition(payload, device_id)
        version = await self.configs.next_version(device_id)
        row = DeviceConfiguration(
            device_id=device_id,
            version=version,
            status=ConfigurationStatus.DRAFT.value,
            protocol=definition.protocol.value,
            configuration=definition.model_dump(mode="json"),
            created_by=actor,
        )
        try:
            await self.configs.create(row)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConfigurationConflictError(
                "another configuration version was created concurrently; retry"
            ) from exc
        self.audit.record(
            device_id=device_id,
            event_type=DRAFT_CREATED,
            version=version,
            summary=f"draft v{version} created for protocol {definition.protocol.value}",
            actor=actor,
        )
        await self.session.commit()
        return row

    async def update_draft(
        self, device_id: str, version: int, payload: dict[str, Any], actor: str
    ) -> DeviceConfiguration:
        row = await self.get_configuration(device_id, version)
        if row.status not in MUTABLE_STATUSES:
            raise ConfigurationImmutableError(
                f"configuration v{version} is {row.status} and cannot be edited; "
                "create a new draft version instead"
            )
        definition = _parse_definition(payload, device_id)
        row.configuration = definition.model_dump(mode="json")
        row.protocol = definition.protocol.value
        row.status = ConfigurationStatus.DRAFT.value
        row.validated_at = None
        row.validation_result = {}
        row.validation_error = None
        await self.session.flush()
        self.audit.record(
            device_id=device_id,
            event_type=DRAFT_UPDATED,
            version=version,
            summary=f"draft v{version} updated",
            actor=actor,
        )
        await self.session.commit()
        return row

    async def delete_draft(self, device_id: str, version: int) -> None:
        row = await self.get_configuration(device_id, version)
        if row.status != ConfigurationStatus.DRAFT.value:
            raise ConfigurationStateError(
                f"configuration v{version} is {row.status}; only DRAFT versions can be deleted"
            )
        await self.configs.delete(row)
        self.audit.record(
            device_id=device_id,
            event_type=DRAFT_DELETED,
            version=version,
            summary=f"draft v{version} deleted",
        )
        await self.session.commit()

    async def clone_version(
        self, device_id: str, source_version: int, actor: str
    ) -> DeviceConfiguration:
        """Create the next draft from an existing snapshot.

        This is also the rollback mechanism: an old snapshot is cloned into a new
        version and published, so the version sequence stays strictly increasing and
        history is never rewritten.
        """

        source = await self.get_configuration(device_id, source_version)
        version = await self.configs.next_version(device_id)
        row = DeviceConfiguration(
            device_id=device_id,
            version=version,
            status=ConfigurationStatus.DRAFT.value,
            protocol=source.protocol,
            configuration=dict(source.configuration),
            created_by=actor,
        )
        await self.configs.create(row)
        rollback = source.status == ConfigurationStatus.ARCHIVED.value
        self.audit.record(
            device_id=device_id,
            event_type=ROLLBACK_DRAFT_CREATED if rollback else DRAFT_CREATED,
            version=version,
            summary=(
                f"draft v{version} cloned from archived v{source_version} (rollback)"
                if rollback
                else f"draft v{version} cloned from v{source_version}"
            ),
            actor=actor,
            extra={"source_version": source_version},
        )
        await self.session.commit()
        return row

    async def validate_version(self, device_id: str, version: int) -> dict[str, Any]:
        """Run the validation pipeline. Never mutates runtime or published state."""

        row = await self.get_configuration(device_id, version)
        device = await self._require_device(device_id)
        outcome = validate_configuration(
            device_id=device_id,
            payload=row.configuration,
            device_status=device.status,
        )
        if row.status in MUTABLE_STATUSES:
            row.validation_result = outcome.as_dict()
            row.validation_error = (
                None if outcome.valid else "; ".join(issue["message"] for issue in outcome.errors)
            )
            if outcome.valid:
                row.status = ConfigurationStatus.VALIDATED.value
                row.validated_at = outcome.checked_at
            await self.session.flush()
            self.audit.record(
                device_id=device_id,
                event_type=VALIDATED,
                version=version,
                status="SUCCESS" if outcome.valid else "FAILED",
                summary=(
                    f"v{version} passed validation"
                    if outcome.valid
                    else f"v{version} failed validation with {len(outcome.errors)} issue(s)"
                ),
                extra={"error_count": len(outcome.errors)},
            )
            await self.session.commit()
        return outcome.as_dict()

    async def publish(
        self, device_id: str, version: int, actor: str
    ) -> tuple[DeviceConfiguration, dict[str, Any]]:
        """Publish a draft, then ask the gateway to apply it.

        The database publish is committed before the apply attempt, so a failed
        application is recorded as drift rather than rolled back into a lie.
        """

        row = await self.get_configuration(device_id, version)
        if row.status == ConfigurationStatus.PUBLISHED.value:
            raise ConfigurationStateError(f"configuration v{version} is already published")
        if row.status == ConfigurationStatus.ARCHIVED.value:
            raise ConfigurationStateError(
                f"configuration v{version} is archived; clone it into a new draft to "
                "roll back or republish"
            )
        device = await self._require_device(device_id)
        outcome = validate_configuration(
            device_id=device_id,
            payload=row.configuration,
            device_status=device.status,
        )
        row.validation_result = outcome.as_dict()
        if not outcome.valid:
            row.validation_error = "; ".join(issue["message"] for issue in outcome.errors)
            await self.session.flush()
            self.audit.record(
                device_id=device_id,
                event_type=VALIDATED,
                version=version,
                status="FAILED",
                summary=f"publish rejected: v{version} failed validation",
                extra={"error_count": len(outcome.errors)},
            )
            await self.session.commit()
            raise ConfigurationValidationError(
                f"configuration v{version} failed validation and was not published",
                outcome.errors,
            )

        published_at = _now()
        # Ordering matters. ``uq_device_configurations_single_published`` admits at
        # most one PUBLISHED row per device, and PostgreSQL evaluates a unique index
        # on every statement, not only at commit. Demoting the incumbent before
        # promoting the successor therefore keeps the invariant true at every
        # intermediate statement inside the transaction.
        archived_count = await self.configs.archive_published_except(device_id, version)
        row.status = ConfigurationStatus.PUBLISHED.value
        row.published_at = published_at
        row.validated_at = outcome.checked_at
        row.validation_error = None
        await self.session.flush()
        self.audit.record(
            device_id=device_id,
            event_type=PUBLISHED,
            version=version,
            summary=f"v{version} published",
            actor=actor,
        )
        if archived_count:
            self.audit.record(
                device_id=device_id,
                event_type=ARCHIVED,
                version=None,
                summary=f"{archived_count} previously published version(s) archived",
            )
        await self.session.commit()

        await self._apply_published(device_id, version, actor)
        status_row = await self.status(device_id)
        return row, status_row

    async def _apply_published(self, device_id: str, version: int, actor: str) -> ApplyOutcome:
        row = await self.configs.get(device_id, version)
        if row is None:  # pragma: no cover - guarded by the caller
            raise ConfigurationNotFoundError(f"configuration v{version} disappeared")
        definition = DeviceDefinition.model_validate(row.configuration)
        if not self.applier.available:
            outcome = ApplyOutcome(
                applied=False,
                applied_version=None,
                error="gateway runtime is not available in this process",
            )
            await self._record_apply(device_id, version, outcome, actor, pending=True)
            return outcome
        await self._mark_applying(device_id, version)
        try:
            outcome = await self.applier.apply(definition, version=version)
        except Exception as exc:
            # A raising applier is a failed apply, not an internal server error. The
            # published version stays published, the runtime stays as it was, and the
            # exception text is recorded as the drift cause.
            outcome = ApplyOutcome(
                applied=False,
                applied_version=None,
                error=f"{type(exc).__name__}: {exc}",
            )
        await self._record_apply(device_id, version, outcome, actor, pending=False)
        return outcome

    async def _mark_applying(self, device_id: str, version: int) -> None:
        """Commit an APPLYING row before the runtime is touched.

        If the process dies mid-apply the row stays APPLYING, which is the honest
        answer, and startup reconciliation overwrites it once the runtime state is
        known again. The previous error text is deliberately preserved so an
        operator watching the attempt still sees why the last one failed.
        """

        existing = await self.configs.runtime_status(device_id)
        await self.configs.upsert_runtime_status(
            device_id=device_id,
            desired_version=version,
            applied_version=self.applier.applied_version(device_id),
            apply_status=ApplyStatus.APPLYING,
            source=ConfigurationSource.DATABASE,
            last_apply_at=_now(),
            last_apply_error=existing.last_apply_error if existing is not None else None,
        )
        await self.session.commit()

    async def _record_apply(
        self,
        device_id: str,
        version: int,
        outcome: ApplyOutcome,
        actor: str,
        *,
        pending: bool,
    ) -> None:
        if outcome.applied:
            apply_status = ApplyStatus.APPLIED
        elif pending:
            apply_status = ApplyStatus.PENDING
        else:
            apply_status = ApplyStatus.FAILED
        applied_version = (
            outcome.applied_version if outcome.applied else self.applier.applied_version(device_id)
        )
        await self.configs.upsert_runtime_status(
            device_id=device_id,
            desired_version=version,
            applied_version=applied_version,
            apply_status=apply_status,
            source=ConfigurationSource.DATABASE,
            last_apply_at=_now(),
            last_apply_error=outcome.error,
        )
        self.audit.record(
            device_id=device_id,
            event_type=(
                APPLY_SUCCEEDED if outcome.applied else APPLY_PENDING if pending else APPLY_FAILED
            ),
            version=version,
            status="SUCCESS" if outcome.applied else ("PENDING" if pending else "FAILED"),
            summary=(
                f"v{version} applied to the runtime"
                if outcome.applied
                else f"v{version} was not applied: {outcome.error or 'unknown cause'}"
            ),
            actor=actor,
            extra={"runtime_state": outcome.runtime_state},
        )
        await self.session.commit()

    async def apply_current(self, device_id: str, actor: str) -> dict[str, Any]:
        """Retry applying the currently published version."""

        await self._require_device(device_id)
        published = await self.configs.current_published(device_id)
        if published is None:
            raise ConfigurationNotFoundError(
                f"device '{device_id}' has no published configuration to apply"
            )
        if not self.applier.available:
            raise ApplyUnavailableError(
                "gateway runtime is not available in this process; "
                "enable the gateway to apply configurations"
            )
        await self._apply_published(device_id, published.version, actor)
        return await self.status(device_id)

    async def status(self, device_id: str) -> dict[str, Any]:
        """Return desired versus applied state for one device."""

        await self._require_device(device_id)
        published = await self.configs.current_published(device_id)
        row = await self.configs.runtime_status(device_id)
        desired = published.version if published is not None else None
        applied = row.applied_version if row is not None else None
        apply_status = ApplyStatus(row.apply_status) if row is not None else ApplyStatus.PENDING
        return {
            "device_id": device_id,
            "desired_version": desired,
            "applied_version": applied,
            "apply_status": apply_status,
            "source": row.source if row is not None else ConfigurationSource.NONE.value,
            "last_apply_at": row.last_apply_at if row is not None else None,
            "last_apply_error": row.last_apply_error if row is not None else None,
            "in_sync": bool(
                desired is not None and desired == applied and apply_status is ApplyStatus.APPLIED
            ),
            "protocol": published.protocol if published is not None else None,
            "runtime_state": self.applier.runtime_state(device_id),
        }

    async def audit_history(self, device_id: str, limit: int) -> list[dict[str, Any]]:
        await self._require_device(device_id)
        rows = await self.audit_reader.list_for_device(device_id, limit)
        return [audit_event_to_read(row) for row in rows]
