"""Phase 6.13-B: the enterprise organization model, end to end.

Everything here runs against real PostgreSQL through the real application,
because the claims are database claims: a binding names a row that must
exist, a device lives in at most one area, cascade deletes remove reach,
and the scope decision is enforced on routes that name a device.

Three groups:

1. Structure and binding APIs — CRUD, validation, audit attribution.
2. Scope policy evaluation — the resolution rules, including the two kinds of
   unrestricted caller and the deny-by-empty answer.
3. Enforcement — a bound operator reaches devices inside their plant and is
   refused, with an audited ``SCOPE_DENIED`` row, on devices outside it.

The documented default matters: an identity with **no** bindings keeps the
global reach every operator had before this phase. A binding, once present,
is exhaustive.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Alarm, AuditEvent, Device, Organization
from app.security.passwords import hash_password
from app.security.repository import RoleRepository, UserRepository
from tests.security.conftest import TEST_PASSWORD

ORGANIZATIONS = "/api/v1/organizations"


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


async def seed_device(sessions: async_sessionmaker[AsyncSession], device_id: str) -> None:
    async with sessions() as session:
        session.add(
            Device(
                device_id=device_id,
                device_type="MOTOR",
                name=device_id,
                status="ACTIVE",
                device_metadata={},
            )
        )
        await session.commit()


async def seed_alarm(sessions: async_sessionmaker[AsyncSession], device_id: str) -> object:
    async with sessions() as session:
        alarm = Alarm(
            device_id=device_id,
            rule_id="temperature_high",
            severity="CRITICAL",
            status="ACTIVE",
            message="95 °C > 90 °C",
            occurrence_count=1,
        )
        session.add(alarm)
        await session.commit()
        return alarm.id


async def events(sessions: async_sessionmaker[AsyncSession], **filters: object) -> list[AuditEvent]:
    async with sessions() as session:
        statement = select(AuditEvent).order_by(AuditEvent.timestamp.asc())
        for column, value in filters.items():
            statement = statement.where(getattr(AuditEvent, column) == value)
        return list(await session.scalars(statement))


async def build_hierarchy(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    admin_token: str,
    *,
    device: str,
) -> tuple[str, str]:
    """Create org → plant → area, assign the device, return (org_id, area_id)."""

    org = (
        await client.post(
            ORGANIZATIONS,
            json={"name": f"Enterprise {uuid4()}", "description": "holding"},
            headers=auth(admin_token),
        )
    ).json()
    plant = (
        await client.post(
            f"{ORGANIZATIONS}/{org['id']}/plants",
            json={"name": "Plant A"},
            headers=auth(admin_token),
        )
    ).json()
    area = (
        await client.post(
            f"/api/v1/plants/{plant['id']}/areas",
            json={"name": "Area 1"},
            headers=auth(admin_token),
        )
    ).json()
    await seed_device(sessions, device)
    assigned = await client.put(
        f"/api/v1/devices/{device}/scope",
        json={"area_id": area["id"]},
        headers=auth(admin_token),
    )
    assert assigned.status_code == 200, assigned.text
    return org["id"], area["id"]


# --------------------------------------------------------------------------- #
# 1. Structure and binding APIs
# --------------------------------------------------------------------------- #


async def test_the_hierarchy_is_authored_over_http(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    created = await client.post(ORGANIZATIONS, json={"name": "Enterprise One"}, headers=auth(token))
    assert created.status_code == 201, created.text
    org = created.json()

    plant = (
        await client.post(
            f"{ORGANIZATIONS}/{org['id']}/plants", json={"name": "Plant A"}, headers=auth(token)
        )
    ).json()
    assert plant["organization_id"] == org["id"]

    area = (
        await client.post(
            f"/api/v1/plants/{plant['id']}/areas", json={"name": "Area 1"}, headers=auth(token)
        )
    ).json()
    assert area["plant_id"] == plant["id"]

    listed = await client.get(f"{ORGANIZATIONS}/{org['id']}/plants", headers=auth(token))
    assert [row["name"] for row in listed.json()] == ["Plant A"]


async def test_a_duplicate_organization_name_is_refused(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    first = await client.post(ORGANIZATIONS, json={"name": "Dup Co"}, headers=auth(token))
    assert first.status_code == 201
    second = await client.post(ORGANIZATIONS, json={"name": "Dup Co"}, headers=auth(token))
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ORGANIZATION_EXISTS"


async def test_deleting_a_plant_cascades_to_its_areas(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Scope is structure: remove the structure and the reach below it goes."""

    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")
    org = (
        await client.post(ORGANIZATIONS, json={"name": "Cascade Co"}, headers=auth(token))
    ).json()
    plant = (
        await client.post(
            f"{ORGANIZATIONS}/{org['id']}/plants", json={"name": "P"}, headers=auth(token)
        )
    ).json()
    area = (
        await client.post(
            f"/api/v1/plants/{plant['id']}/areas", json={"name": "A"}, headers=auth(token)
        )
    ).json()

    deleted = await client.delete(f"/api/v1/plants/{plant['id']}", headers=auth(token))
    assert deleted.status_code == 204
    gone = await client.get(f"/api/v1/plants/{plant['id']}/areas", headers=auth(token))
    assert gone.status_code == 404
    missing = await client.get(f"/api/v1/areas/{area['id']}", headers=auth(token))
    assert missing.status_code == 404


async def test_user_scope_binding_replaces_wholesale(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    org = (
        await client.post(ORGANIZATIONS, json={"name": "Binding Co"}, headers=auth(token))
    ).json()

    bound = await client.put(
        f"/api/v1/users/{user_id}/scopes",
        json={"bindings": [{"scope_level": "ORGANIZATION", "scope_id": org["id"]}]},
        headers=auth(token),
    )
    assert bound.status_code == 200, bound.text
    assert len(bound.json()) == 1

    cleared = await client.put(
        f"/api/v1/users/{user_id}/scopes", json={"bindings": []}, headers=auth(token)
    )
    assert cleared.status_code == 200
    assert cleared.json() == []


async def test_a_binding_to_a_nonexistent_scope_is_refused(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")

    response = await client.put(
        f"/api/v1/users/{user_id}/scopes",
        json={"bindings": [{"scope_level": "PLANT", "scope_id": str(uuid4())}]},
        headers=auth(token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLANT_NOT_FOUND"


async def test_device_scope_requires_a_known_device_and_area(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    unknown_device = await client.put(
        "/api/v1/devices/MOTOR-999/scope", json={"area_id": None}, headers=auth(token)
    )
    assert unknown_device.status_code == 404
    assert unknown_device.json()["error"]["code"] == "DEVICE_NOT_FOUND"

    unknown_area = await client.put(
        "/api/v1/devices/MOTOR-001/scope",
        json={"area_id": str(uuid4())},
        headers=auth(token),
    )
    assert unknown_area.status_code == 404
    assert unknown_area.json()["error"]["code"] == "AREA_NOT_FOUND"


async def test_the_structure_mutations_are_attributed(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await make_user(sessions, "admin.one", "ADMIN")
    token = await token_for(client, "admin.one")

    await client.post(ORGANIZATIONS, json={"name": "Attributed Co"}, headers=auth(token))

    rows = await events(sessions, action="ORGANIZATION_CREATED")
    assert len(rows) == 1
    assert rows[0].actor == "admin.one"
    assert rows[0].actor_user_id == user_id


async def test_the_scope_surface_requires_scope_manage(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """``scope.manage`` defaults to ADMIN only, so an operator is refused."""

    await make_user(sessions, "operator.one", "OPERATOR")
    token = await token_for(client, "operator.one")

    response = await client.put(
        f"/api/v1/users/{uuid4()}/scopes", json={"bindings": []}, headers=auth(token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_permission"] == "scope.manage"


# --------------------------------------------------------------------------- #
# 2. Enforcement on the business surface
# --------------------------------------------------------------------------- #


async def bind(client: AsyncClient, admin_token: str, user_id: object, area_id: str) -> None:
    response = await client.put(
        f"/api/v1/users/{user_id}/scopes",
        json={"bindings": [{"scope_level": "AREA", "scope_id": area_id}]},
        headers=auth(admin_token),
    )
    assert response.status_code == 200, response.text


async def test_a_bound_operator_reaches_in_scope_devices_and_is_refused_outside(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The headline of the phase: reach follows the hierarchy, end to end."""

    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")

    _, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, area_id)
    await seed_device(sessions, "MOTOR-OUT")
    in_alarm = await seed_alarm(sessions, "MOTOR-IN")
    out_alarm = await seed_alarm(sessions, "MOTOR-OUT")

    inside = await client.post(
        f"/api/v1/alarms/{in_alarm}/acknowledge", json={}, headers=auth(operator_token)
    )
    assert inside.status_code == 200, inside.text

    outside = await client.post(
        f"/api/v1/alarms/{out_alarm}/acknowledge", json={}, headers=auth(operator_token)
    )
    assert outside.status_code == 403
    body = outside.json()["error"]
    assert body["code"] == "SCOPE_DENIED"
    assert body["details"]["device_id"] == "MOTOR-OUT"


async def test_the_refusal_is_audited_with_the_identity(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    _, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, area_id)
    out_alarm = await seed_alarm(sessions, "MOTOR-OUT")

    await client.post(
        f"/api/v1/alarms/{out_alarm}/acknowledge", json={}, headers=auth(operator_token)
    )

    rows = await events(sessions, action="SCOPE_DENIED")
    assert len(rows) == 1
    assert rows[0].actor == "operator.one"
    assert rows[0].actor_user_id == user_id
    assert rows[0].resource_id == "MOTOR-OUT"
    assert rows[0].status == "DENIED"


async def test_a_bound_operator_sees_only_in_scope_alarms(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    _, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, area_id)
    await seed_alarm(sessions, "MOTOR-IN")
    await seed_alarm(sessions, "MOTOR-OUT")

    listed = await client.get("/api/v1/alarms", headers=auth(operator_token))

    devices = {row["device_id"] for row in listed.json()}
    assert devices == {"MOTOR-IN"}


async def test_an_unbound_operator_keeps_global_reach(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The documented migration default: no bindings, no shrinkage."""

    await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    await seed_device(sessions, "MOTOR-ANYWHERE")
    alarm_id = await seed_alarm(sessions, "MOTOR-ANYWHERE")

    response = await client.post(
        f"/api/v1/alarms/{alarm_id}/acknowledge", json={}, headers=auth(operator_token)
    )

    assert response.status_code == 200, response.text


async def test_an_administrator_with_bindings_is_still_unrestricted(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    _, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")

    await client.put(
        f"/api/v1/users/{await _admin_id(sessions, 'admin.one')}/scopes",
        json={"bindings": [{"scope_level": "AREA", "scope_id": area_id}]},
        headers=auth(admin_token),
    )
    out_alarm = await seed_alarm(sessions, "MOTOR-OUT")

    response = await client.post(
        f"/api/v1/alarms/{out_alarm}/acknowledge", json={}, headers=auth(admin_token)
    )

    assert response.status_code == 200, response.text


async def _admin_id(sessions: async_sessionmaker[AsyncSession], username: str) -> object:
    async with sessions() as session:
        from sqlalchemy import select

        from app.security.models import User

        return await session.scalar(select(User.id).where(User.username == username))


async def test_scope_denial_never_mutates_the_refused_resource(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    _, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, area_id)
    out_alarm = await seed_alarm(sessions, "MOTOR-OUT")

    await client.post(
        f"/api/v1/alarms/{out_alarm}/acknowledge", json={}, headers=auth(operator_token)
    )

    async with sessions() as session:
        alarm = await session.get(Alarm, out_alarm)
        assert alarm is not None
        assert alarm.status == "ACTIVE"
        assert alarm.acknowledged_by is None


async def test_configuration_routes_honour_the_scope(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Device-scoped reads are refused outside the subtree, not just writes."""

    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, await _first_area_id(client, admin_token))

    response = await client.get(
        "/api/v1/devices/MOTOR-OUT/configurations", headers=auth(operator_token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SCOPE_DENIED"


async def _first_area_id(client: AsyncClient, admin_token: str) -> str:
    orgs = (await client.get(ORGANIZATIONS, headers=auth(admin_token))).json()
    plants = (
        await client.get(f"{ORGANIZATIONS}/{orgs[0]['id']}/plants", headers=auth(admin_token))
    ).json()
    areas = (
        await client.get(f"/api/v1/plants/{plants[0]['id']}/areas", headers=auth(admin_token))
    ).json()
    return str(areas[0]["id"])


async def test_the_organization_read_model_stays_visible_to_every_role(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """``org.read`` is granted to every role: structure is not a secret."""

    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    await client.post(ORGANIZATIONS, json={"name": "Visible Co"}, headers=auth(admin_token))

    await make_user(sessions, "viewer.one", "VIEWER")
    viewer_token = await token_for(client, "viewer.one")

    response = await client.get(ORGANIZATIONS, headers=auth(viewer_token))

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == ["Visible Co"]


async def test_deleting_an_organization_removes_the_reach_it_granted(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Cascade is a governance act, observable as revoked device reach."""

    await make_user(sessions, "admin.one", "ADMIN")
    admin_token = await token_for(client, "admin.one")
    user_id = await make_user(sessions, "operator.one", "OPERATOR")
    operator_token = await token_for(client, "operator.one")
    org_id, area_id = await build_hierarchy(client, sessions, admin_token, device="MOTOR-IN")
    await bind(client, admin_token, user_id, area_id)
    alarm_id = await seed_alarm(sessions, "MOTOR-IN")
    assert (
        await client.post(
            f"/api/v1/alarms/{alarm_id}/acknowledge", json={}, headers=auth(operator_token)
        )
    ).status_code == 200

    await client.delete(f"{ORGANIZATIONS}/{org_id}", headers=auth(admin_token))

    refused = await client.post(
        f"/api/v1/alarms/{alarm_id}/clear", json={}, headers=auth(operator_token)
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "SCOPE_DENIED"


async def test_the_row_survives_in_the_organizations_table_by_name(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """A structural check that the model is the real PostgreSQL table."""

    async with sessions() as session:
        row = Organization(name="Model Check Co", description="")
        session.add(row)
        await session.commit()
        found = await session.get(Organization, row.id)
        assert found is not None
        assert found.name == "Model Check Co"
