"""Phase 6.13-C: enterprise governance and compliance, end to end.

Everything here runs against real PostgreSQL through the real application,
because the claims are database claims: a policy that refuses a permission
must leave an audited ``POLICY_DENIED`` row; a change record must refuse an
illegal lifecycle transition; the governance audit view must read the one
``audit_events`` table, not a copy.

Four groups:

1. Policy management — CRUD validation, gating by ``governance.manage``, and
   the what-if evaluate endpoint.
2. Policy enforcement — the engine refuses above RBAC, audits before the 403,
   honours the enabled flag, and treats an inert (malformed) rule as a
   match-failure rather than a crash.
3. Change management — lifecycle state machine, scheduling window rules,
   draft-only edits, and attribution.
4. Audit governance and compliance dashboard — filtered queries, the
   security-event slice, and the aggregates.

Pure-function tests for the condition matcher run without the database; they
are in this file because they belong to the same phase contract.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import AuditEvent, ChangeRecord, GovernancePolicy
from app.security.audit import ACTION_POLICY_DENIED, SECURITY_EVENT_ACTIONS
from app.security.governance_models import ChangeStatus
from app.security.passwords import hash_password
from app.security.policy_engine import _conditions_match
from app.security.rbac import Principal
from app.security.repository import RoleRepository, UserRepository
from tests.security.conftest import TEST_PASSWORD

GOVERNANCE = "/api/v1/governance"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_user(sessions: async_sessionmaker[AsyncSession], username: str, role: str) -> object:
    async with sessions() as session:
        user = await UserRepository(session).create(
            username=username, password_hash=hash_password(TEST_PASSWORD)
        )
        await RoleRepository(session).assign(user.id, role)
        await session.commit()
        return user.id


async def token_for(client: AsyncClient, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


async def events(sessions: async_sessionmaker[AsyncSession], **filters: object) -> list[AuditEvent]:
    async with sessions() as session:
        statement = select(AuditEvent).order_by(AuditEvent.timestamp.asc())
        for column, value in filters.items():
            statement = statement.where(getattr(AuditEvent, column) == value)
        return list(await session.scalars(statement))


async def seed_policy(
    sessions: async_sessionmaker[AsyncSession], **overrides: Any
) -> GovernancePolicy:
    """Insert a policy row directly, for cases the API deliberately refuses."""

    defaults: dict[str, Any] = {
        "name": f"direct-{uuid4()}",
        "description": "",
        "effect": "DENY",
        "permission": "change.manage",
        "conditions": {"always": True},
        "enabled": True,
    }
    defaults.update(overrides)
    async with sessions() as session:
        row = GovernancePolicy(**defaults)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


# --------------------------------------------------------------------------- #
# Pure-function condition matching (no database)
# --------------------------------------------------------------------------- #


def _principal(*roles: str) -> Principal:
    return Principal(user_id=uuid4(), username="p", roles=roles, permissions=frozenset())


def test_an_empty_condition_set_never_matches() -> None:
    assert _conditions_match({}, _principal("OPERATOR"), datetime.now(UTC)) is False


def test_an_always_condition_matches_everyone() -> None:
    conditions = {"always": True}
    assert _conditions_match(conditions, _principal("ADMIN"), datetime.now(UTC))
    assert _conditions_match(conditions, _principal("VIEWER"), datetime.now(UTC))


def test_an_always_condition_with_other_keys_is_rejected_shape() -> None:
    # The API refuses this combination; the matcher would evaluate each key.
    conditions = {"always": True, "roles": ["OPERATOR"]}
    assert _conditions_match(conditions, _principal("OPERATOR"), datetime.now(UTC))


def test_a_roles_condition_matches_any_held_role() -> None:
    conditions = {"roles": ["OPERATOR", "ADMIN"]}
    assert _conditions_match(conditions, _principal("OPERATOR"), datetime.now(UTC))
    assert not _conditions_match(conditions, _principal("VIEWER"), datetime.now(UTC))


def test_a_time_window_matches_inside_and_wraps_midnight() -> None:
    # Wednesday 2026-01-07, 10:30 UTC.
    moment = datetime(2026, 1, 7, 10, 30, tzinfo=UTC)
    inside = {"time_window": {"days": [3], "start": "09:00", "end": "17:00"}}
    assert _conditions_match(inside, _principal("OPERATOR"), moment)
    outside = {"time_window": {"days": [3], "start": "01:00", "end": "02:00"}}
    assert not _conditions_match(outside, _principal("OPERATOR"), moment)
    # 23:30 inside a 22:00-04:00 window that wraps midnight.
    late = datetime(2026, 1, 7, 23, 30, tzinfo=UTC)
    overnight = {"time_window": {"days": [3], "start": "22:00", "end": "04:00"}}
    assert _conditions_match(overnight, _principal("OPERATOR"), late)
    # The wrapping window still respects its day list.
    monday = datetime(2026, 1, 5, 23, 30, tzinfo=UTC)
    assert not _conditions_match(overnight, _principal("OPERATOR"), monday)


def test_an_unknown_condition_kind_is_inert() -> None:
    conditions = {"typo_key": True}
    assert not _conditions_match(conditions, _principal("ADMIN"), datetime.now(UTC))


# --------------------------------------------------------------------------- #
# Policy management
# --------------------------------------------------------------------------- #


async def test_policy_crud_is_gated_and_validated(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin_token = await token_for(client, "gov.admin")
    operator_token = await token_for(client, "gov.operator")

    # An operator holds no governance.manage: authoring policy is ADMIN-only.
    forbidden = await client.post(
        f"{GOVERNANCE}/policies",
        json={"name": "operator-rule", "permission": "change.manage"},
        headers=auth(operator_token),
    )
    assert forbidden.status_code == 403

    # An unknown permission name cannot be governed.
    unknown = await client.post(
        f"{GOVERNANCE}/policies",
        json={"name": "bad-rule", "permission": "not.a.permission"},
        headers=auth(admin_token),
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "POLICY_PERMISSION_UNKNOWN"

    # A typo in the conditions must fail at write time, not go inert in prod.
    typo = await client.post(
        f"{GOVERNANCE}/policies",
        json={
            "name": "typo-rule",
            "permission": "change.manage",
            "conditions": {"rolse": ["OPERATOR"]},
        },
        headers=auth(admin_token),
    )
    assert typo.status_code == 422
    assert typo.json()["error"]["code"] == "POLICY_CONDITION_INVALID"

    created = await client.post(
        f"{GOVERNANCE}/policies",
        json={
            "name": "freeze-during-audit",
            "description": "Change freeze",
            "permission": "change.manage",
            "conditions": {"roles": ["OPERATOR"]},
        },
        headers=auth(admin_token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["effect"] == "DENY"
    assert body["enabled"] is True
    policy_id = body["id"]

    duplicate = await client.post(
        f"{GOVERNANCE}/policies",
        json={"name": "freeze-during-audit", "permission": "change.manage"},
        headers=auth(admin_token),
    )
    assert duplicate.status_code == 409

    listed = await client.get(f"{GOVERNANCE}/policies", headers=auth(admin_token))
    assert listed.status_code == 200
    assert any(row["id"] == policy_id for row in listed.json())

    updated = await client.patch(
        f"{GOVERNANCE}/policies/{policy_id}",
        json={"enabled": False},
        headers=auth(admin_token),
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False

    deleted = await client.delete(f"{GOVERNANCE}/policies/{policy_id}", headers=auth(admin_token))
    assert deleted.status_code == 204
    gone = await client.get(f"{GOVERNANCE}/policies/{policy_id}", headers=auth(admin_token))
    assert gone.status_code == 404


async def test_the_evaluate_endpoint_answers_without_changing_anything(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin_token = await token_for(client, "gov.evaluator")
    await seed_policy(sessions, permission="change.manage", conditions={"roles": ["OPERATOR"]})

    operator_token = await token_for(client, "gov.evaluated")
    denied = await client.post(
        f"{GOVERNANCE}/policies/evaluate",
        json={"permission": "change.manage"},
        headers=auth(operator_token),
    )
    assert denied.status_code == 200
    body = denied.json()
    assert body["allowed"] is False
    assert body["policy_name"] is not None

    allowed = await client.post(
        f"{GOVERNANCE}/policies/evaluate",
        json={"permission": "change.manage"},
        headers=auth(admin_token),
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True


# --------------------------------------------------------------------------- #
# Policy enforcement
# --------------------------------------------------------------------------- #


async def _create_change(client: AsyncClient, token: str) -> Response:
    return await client.post(
        f"{GOVERNANCE}/changes",
        json={
            "title": "Replace PLC firmware",
            "change_type": "HARDWARE",
            "risk_level": "MEDIUM",
        },
        headers=auth(token),
    )


async def test_a_policy_refuses_above_rbac_and_leaves_evidence(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin_token = await token_for(client, "gov.enforcer")
    operator_token = await token_for(client, "gov.constrained")

    created = await client.post(
        f"{GOVERNANCE}/policies",
        json={
            "name": "no-operator-changes",
            "permission": "change.manage",
            "conditions": {"roles": ["OPERATOR"]},
        },
        headers=auth(admin_token),
    )
    assert created.status_code == 201

    refused = await _create_change(client, operator_token)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "POLICY_DENIED"

    # The refusal is audited with the acting identity before the 403.
    denials = await events(sessions, action=ACTION_POLICY_DENIED, actor="gov.constrained")
    assert len(denials) == 1
    assert denials[0].actor_user_id is not None
    assert denials[0].details["policy"] == "no-operator-changes"

    # The admin's roles are outside the condition, so RBAC alone decides.
    permitted = await _create_change(client, admin_token)
    assert permitted.status_code == 201, permitted.text

    # Disabling the policy restores the RBAC answer without deleting it.
    policy_id = created.json()["id"]
    disabled = await client.patch(
        f"{GOVERNANCE}/policies/{policy_id}",
        json={"enabled": False},
        headers=auth(admin_token),
    )
    assert disabled.status_code == 200
    after_disable = await _create_change(client, operator_token)
    assert after_disable.status_code == 201


async def test_an_always_policy_binds_even_the_administrator(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A change freeze is governance above RBAC; nobody is exempt."""

    admin_token = await token_for(client, "gov.freeze")
    created = await client.post(
        f"{GOVERNANCE}/policies",
        json={
            "name": "platform-freeze",
            "permission": "change.manage",
            "conditions": {"always": True},
        },
        headers=auth(admin_token),
    )
    assert created.status_code == 201

    refused = await _create_change(client, admin_token)
    assert refused.status_code == 403

    # The admin can still author governance: the freeze targets change.manage.
    released = await client.delete(
        f"{GOVERNANCE}/policies/{created.json()['id']}", headers=auth(admin_token)
    )
    assert released.status_code == 204
    permitted = await _create_change(client, admin_token)
    assert permitted.status_code == 201


async def test_a_malformed_stored_condition_is_inert_not_fatal(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A rule edited out-of-band must degrade to no-op, never to a 500."""

    operator_token = await token_for(client, "gov.resilient")
    await seed_policy(sessions, conditions={"bogus": ["x"]}, enabled=True)

    response = await _create_change(client, operator_token)
    assert response.status_code == 201


# --------------------------------------------------------------------------- #
# Change management
# --------------------------------------------------------------------------- #


async def test_change_lifecycle_enforces_its_state_machine(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    operator_token = await token_for(client, "gov.changer")

    created = await _create_change(client, operator_token)
    assert created.status_code == 201, created.text
    change_id = created.json()["id"]
    assert created.json()["status"] == "DRAFT"
    assert created.json()["requested_by_name"] == "gov.changer"

    # A draft cannot jump straight to execution.
    skip = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "IN_PROGRESS"},
        headers=auth(operator_token),
    )
    assert skip.status_code == 409
    assert skip.json()["error"]["code"] == "INVALID_CHANGE_TRANSITION"

    # Scheduling requires an execution window.
    no_window = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "SCHEDULED"},
        headers=auth(operator_token),
    )
    assert no_window.status_code == 422
    assert no_window.json()["error"]["code"] == "CHANGE_WINDOW_REQUIRED"

    # A window that ends before it starts is refused.
    bad_window = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={
            "status": "SCHEDULED",
            "scheduled_start": "2026-10-01T10:00:00Z",
            "scheduled_end": "2026-10-01T09:00:00Z",
        },
        headers=auth(operator_token),
    )
    assert bad_window.status_code == 422
    assert bad_window.json()["error"]["code"] == "CHANGE_WINDOW_INVALID"

    scheduled = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={
            "status": "SCHEDULED",
            "scheduled_start": "2026-10-01T10:00:00Z",
            "scheduled_end": "2026-10-01T12:00:00Z",
        },
        headers=auth(operator_token),
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["status"] == "SCHEDULED"

    # A scheduled record is the plan people may have acted on: no edits.
    edited = await client.patch(
        f"{GOVERNANCE}/changes/{change_id}",
        json={"title": "Retitle after scheduling"},
        headers=auth(operator_token),
    )
    assert edited.status_code == 409
    assert edited.json()["error"]["code"] == "CHANGE_NOT_EDITABLE"

    # A window may only be supplied when scheduling.
    window_elsewhere = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "IN_PROGRESS", "scheduled_start": "2026-10-02T10:00:00Z"},
        headers=auth(operator_token),
    )
    assert window_elsewhere.status_code == 409

    started = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "IN_PROGRESS"},
        headers=auth(operator_token),
    )
    assert started.status_code == 200

    completed = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "COMPLETED"},
        headers=auth(operator_token),
    )
    assert completed.status_code == 200

    # A completed record is history; it cannot resurrect.
    resurrect = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "IN_PROGRESS"},
        headers=auth(operator_token),
    )
    assert resurrect.status_code == 409

    transitions = await events(sessions, action="CHANGE_RECORD_TRANSITIONED")
    assert [(t.details["from"], t.details["to"]) for t in transitions] == [
        ("DRAFT", "SCHEDULED"),
        ("SCHEDULED", "IN_PROGRESS"),
        ("IN_PROGRESS", "COMPLETED"),
    ]


async def test_change_listing_filters_and_role_gating(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    operator_token = await token_for(client, "gov.lister")
    viewer_token = await token_for(client, "gov.observer")

    for title, risk in (("low change", "LOW"), ("high change", "HIGH")):
        response = await client.post(
            f"{GOVERNANCE}/changes",
            json={"title": title, "change_type": "CONFIGURATION", "risk_level": risk},
            headers=auth(operator_token),
        )
        assert response.status_code == 201

    # A viewer reads the ledger but never writes it.
    readable = await client.get(f"{GOVERNANCE}/changes", headers=auth(viewer_token))
    assert readable.status_code == 200
    viewer_write = await _create_change(client, viewer_token)
    assert viewer_write.status_code == 403

    by_risk = await client.get(
        f"{GOVERNANCE}/changes", params={"risk_level": "HIGH"}, headers=auth(operator_token)
    )
    assert by_risk.status_code == 200
    assert [row["title"] for row in by_risk.json()] == ["high change"]

    by_status = await client.get(
        f"{GOVERNANCE}/changes", params={"status": "DRAFT"}, headers=auth(operator_token)
    )
    assert by_status.status_code == 200
    assert {row["status"] for row in by_status.json()} == {"DRAFT"}


async def test_cancelling_a_scheduled_change_is_a_legal_exit(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    operator_token = await token_for(client, "gov.canceller")
    created = await _create_change(client, operator_token)
    change_id = created.json()["id"]

    scheduled = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={
            "status": "SCHEDULED",
            "scheduled_start": "2026-10-05T08:00:00Z",
            "scheduled_end": "2026-10-05T09:00:00Z",
        },
        headers=auth(operator_token),
    )
    assert scheduled.status_code == 200
    cancelled = await client.post(
        f"{GOVERNANCE}/changes/{change_id}/transition",
        json={"status": "CANCELLED"},
        headers=auth(operator_token),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


# --------------------------------------------------------------------------- #
# Audit governance and compliance dashboard
# --------------------------------------------------------------------------- #


async def test_audit_query_filters_the_one_trail(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    operator_token = await token_for(client, "gov.auditor")
    await _create_change(client, operator_token)

    response = await client.get(
        f"{GOVERNANCE}/audit",
        params={"action": "CHANGE_RECORD_CREATED"},
        headers=auth(operator_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(row["action"] == "CHANGE_RECORD_CREATED" for row in body["items"])
    assert body["items"][0]["actor"] == "gov.auditor"

    by_status = await client.get(
        f"{GOVERNANCE}/audit", params={"status": "SUCCESS"}, headers=auth(operator_token)
    )
    assert by_status.status_code == 200
    assert by_status.json()["total"] >= 1

    # A viewer holds no audit.read: the trail carries source addresses.
    viewer_token = await token_for(client, "gov.peeper")
    forbidden = await client.get(f"{GOVERNANCE}/audit", headers=auth(viewer_token))
    assert forbidden.status_code == 403

    unauthenticated = await client.get(f"{GOVERNANCE}/audit")
    assert unauthenticated.status_code == 401

    invalid_window = await client.get(
        f"{GOVERNANCE}/audit", params={"since": "not-a-date"}, headers=auth(operator_token)
    )
    assert invalid_window.status_code == 422


async def test_security_events_are_the_boundary_slice(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    operator_token = await token_for(client, "gov.guard")

    # One refused permission: a viewer calling a manage surface.
    viewer_token = await token_for(client, "gov.intruder")
    await client.post(
        f"{GOVERNANCE}/policies",
        json={"name": "intruder-rule", "permission": "change.manage"},
        headers=auth(viewer_token),
    )

    response = await client.get(f"{GOVERNANCE}/security-events", headers=auth(operator_token))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(row["action"] in SECURITY_EVENT_ACTIONS for row in body["items"])
    assert "PERMISSION_DENIED" in body["summary"]
    assert body["summary"]["PERMISSION_DENIED"]["DENIED"] >= 1
    assert "AUTH_LOGIN" in body["summary"]


async def test_the_compliance_dashboard_aggregates_existing_tables(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin_token = await token_for(client, "gov.dash.admin")
    operator_token = await token_for(client, "gov.dash.operator")

    await _create_change(client, operator_token)
    await client.post(
        f"{GOVERNANCE}/policies",
        json={
            "name": "dash-rule",
            "permission": "change.manage",
            "conditions": {"roles": ["VIEWER"]},
        },
        headers=auth(admin_token),
    )

    response = await client.get(
        f"{GOVERNANCE}/compliance/dashboard",
        params={"window_days": 30},
        headers=auth(admin_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window_days"] == 30
    assert body["audit"]["total"] >= 1
    assert body["audit"]["by_status"]["SUCCESS"] >= 1
    assert body["policies"]["total"] == 1
    assert body["policies"]["enabled"] == 1
    assert body["changes"]["by_status"][ChangeStatus.DRAFT.value] >= 1
    assert body["changes"]["total"] >= 1
    assert body["identities"]["users"] >= 2
    assert body["last_audit_at"] is not None

    # Every role with governance.read sees it, including the viewer.
    viewer_token = await token_for(client, "gov.dash.viewer")
    readable = await client.get(f"{GOVERNANCE}/compliance/dashboard", headers=auth(viewer_token))
    assert readable.status_code == 200

    # The window is bounded.
    too_wide = await client.get(
        f"{GOVERNANCE}/compliance/dashboard",
        params={"window_days": 91},
        headers=auth(admin_token),
    )
    assert too_wide.status_code == 422


async def test_the_change_window_index_exists(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The schema ships the indexes the dashboard and filters rely on."""

    from sqlalchemy import text

    async with sessions() as session:
        result = await session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename IN ('governance_policies', 'change_records')"
            )
        )
        indexes = {row[0] for row in result}
    assert "ix_governance_policies_enabled" in indexes
    assert "ix_change_records_status" in indexes
    assert "ix_change_records_window" in indexes


async def test_change_records_cannot_violate_the_window_check(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The database itself refuses an inverted window, not just the API."""

    async with sessions() as session:
        session.add(
            ChangeRecord(
                title="inverted",
                change_type="CONFIGURATION",
                risk_level="LOW",
                status="SCHEDULED",
                scheduled_start=datetime.now(UTC) + timedelta(hours=2),
                scheduled_end=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        else:
            raise AssertionError("the database accepted an inverted change window")
