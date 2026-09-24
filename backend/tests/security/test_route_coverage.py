"""Every governed route declares the permission it enforces.

This test exists because of a real defect found while documenting Phase 6.12:
``POST /incidents`` and ``GET /incidents/{incident_id}`` were reachable with no
identity at all. The permission dependency had been written and imported, but
never attached to those two routes. A behavioural test per endpoint would not
have caught the next one, so this walks the route table instead and compares it
against the documented matrix.

Four properties are checked.

1. The governed surface (incidents, workflows, approvals, work orders) matches
   the matrix exactly. A route added without a permission, or with the wrong
   one, fails the build rather than shipping an open door.
2. The walk below sees every path the OpenAPI schema advertises, so the
   introspection cannot quietly miss routes and pass by omission.
3. The legacy ``/api`` mirror enforces exactly what ``/api/v1`` enforces, so a
   second prefix cannot become a softer entrance to the same operation.
4. Every declared permission is a name from the vocabulary. A typo such as
   ``incident.acknowledge`` would otherwise create a route nobody can call.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.routing import APIRoute

from app.main import app
from app.security.rbac import (
    ALL_PERMISSIONS,
    APPROVAL_READ,
    APPROVAL_REVIEW,
    INCIDENT_ACK,
    INCIDENT_CLOSE,
    INCIDENT_CREATE,
    INCIDENT_INVESTIGATE,
    INCIDENT_READ,
    INCIDENT_REOPEN,
    INCIDENT_RESOLVE,
    WILDCARD,
    WORKFLOW_CANCEL,
    WORKFLOW_READ,
    WORKFLOW_START,
    WORKORDER_READ,
)

#: Prefixes whose routes operate on governed objects. Matching is by prefix
#: rather than by exact path so ``/api/v1/workflow-metrics`` is covered too.
GOVERNED_PREFIXES = (
    "/api/v1/incident",
    "/api/v1/workflow",
    "/api/v1/approval",
    "/api/v1/work-order",
    "/api/incident",
    "/api/workflow",
    "/api/approval",
    "/api/work-order",
)

#: The documented matrix. Written out in full rather than derived from the code,
#: because a derived expectation would simply agree with whatever the code does.
EXPECTED: dict[tuple[str, str], str] = {
    # Incident lifecycle.
    ("POST", "/api/v1/incidents"): INCIDENT_CREATE,
    ("GET", "/api/v1/incidents"): INCIDENT_READ,
    ("GET", "/api/v1/incidents/{incident_id}"): INCIDENT_READ,
    ("GET", "/api/v1/incidents/dashboard"): INCIDENT_READ,
    ("GET", "/api/v1/incidents/metrics"): INCIDENT_READ,
    ("GET", "/api/v1/incidents/{incident_id}/context"): INCIDENT_READ,
    ("GET", "/api/v1/incidents/{incident_id}/workflow-context"): INCIDENT_READ,
    ("POST", "/api/v1/incidents/{incident_id}/acknowledge"): INCIDENT_ACK,
    ("POST", "/api/v1/incidents/{incident_id}/investigate"): INCIDENT_INVESTIGATE,
    ("POST", "/api/v1/incidents/{incident_id}/resolve"): INCIDENT_RESOLVE,
    ("POST", "/api/v1/incidents/{incident_id}/close"): INCIDENT_CLOSE,
    ("POST", "/api/v1/incidents/{incident_id}/reopen"): INCIDENT_REOPEN,
    # Workflow execution.
    ("POST", "/api/v1/incidents/{incident_id}/start-workflow"): WORKFLOW_START,
    ("POST", "/api/v1/incidents/{incident_id}/workflows"): WORKFLOW_START,
    ("GET", "/api/v1/workflow-metrics"): WORKFLOW_READ,
    ("GET", "/api/v1/workflows"): WORKFLOW_READ,
    ("GET", "/api/v1/workflows/{workflow_run_id}"): WORKFLOW_READ,
    ("GET", "/api/v1/workflows/{workflow_run_id}/trace"): WORKFLOW_READ,
    ("POST", "/api/v1/workflows/{workflow_run_id}/cancel"): WORKFLOW_CANCEL,
    # Human approval gate.
    ("GET", "/api/v1/approvals/pending"): APPROVAL_READ,
    ("GET", "/api/v1/approvals/{approval_id}"): APPROVAL_READ,
    ("POST", "/api/v1/approvals/{approval_id}/approve"): APPROVAL_REVIEW,
    ("POST", "/api/v1/approvals/{approval_id}/reject"): APPROVAL_REVIEW,
    # Maintenance outcome.
    ("GET", "/api/v1/work-orders"): WORKORDER_READ,
    ("GET", "/api/v1/work-orders/{work_order_id}"): WORKORDER_READ,
}


def _is_governed(path: str) -> bool:
    return path.startswith(GOVERNED_PREFIXES)


def _permissions_of(dependant: object) -> frozenset[str]:
    """Collect every permission declared anywhere in a route's dependency tree."""

    found: set[str] = set()
    for sub in getattr(dependant, "dependencies", []):
        permission = getattr(sub.call, "security_permission", None)
        if isinstance(permission, str):
            found.add(permission)
        found |= _permissions_of(sub)
    return frozenset(found)


def _iter_routes(container: object, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Yield every HTTP route with the prefix its include() applied.

    FastAPI 0.141 keeps included routers nested rather than flattening them into
    ``app.routes``, and the include prefix lives on the wrapper's context, not on
    the sub-router's ``route.path``. Walking that structure is the only way to see
    the path a client actually calls. ``test_the_walk_sees_every_documented_path``
    is what keeps this honest if the internals move again.
    """

    for entry in getattr(container, "routes", []):
        if isinstance(entry, APIRoute):
            yield f"{prefix}{entry.path}", entry
            continue
        sub = getattr(entry, "original_router", None)
        context = getattr(entry, "include_context", None)
        if sub is None or context is None:
            continue
        include_prefix = getattr(context, "prefix", "") or ""
        yield from _iter_routes(sub, f"{prefix}{include_prefix}")


def _route_table() -> dict[tuple[str, str], frozenset[str]]:
    table: dict[tuple[str, str], frozenset[str]] = {}
    for path, route in _iter_routes(app):
        for method in route.methods or ():
            table[(method, path)] = _permissions_of(route.dependant)
    return table


def test_the_walk_sees_every_documented_path() -> None:
    """The introspection must not pass by missing routes.

    A route the walker cannot see is a route this file cannot police, so the
    walk is cross-checked against the OpenAPI schema, which is public API.
    """

    documented = set(app.openapi()["paths"])
    walked = {path for path, _ in _iter_routes(app)}
    invisible = {path for path in documented if path not in walked}
    assert not invisible, f"routes exist that the permission walk cannot see: {sorted(invisible)}"


def test_the_governed_surface_matches_the_documented_matrix() -> None:
    table = _route_table()
    versioned = {
        key: permissions
        for key, permissions in table.items()
        if key[1].startswith("/api/v1/") and _is_governed(key[1])
    }

    assert set(versioned) == set(EXPECTED), (
        "governed routes changed; update the security model and this matrix together: "
        f"missing={sorted(set(EXPECTED) - set(versioned))} "
        f"unexpected={sorted(set(versioned) - set(EXPECTED))}"
    )
    for key, permission in EXPECTED.items():
        assert versioned[key] == frozenset({permission}), (
            f"{key[0]} {key[1]} must require {permission}, "
            f"declares {sorted(versioned[key]) or 'nothing'}"
        )


def test_incident_creation_and_detail_are_gated() -> None:
    """The two routes that were found open during Phase 6.12 stay closed."""

    table = _route_table()
    assert table[("POST", "/api/v1/incidents")] == frozenset({INCIDENT_CREATE})
    assert table[("GET", "/api/v1/incidents/{incident_id}")] == frozenset({INCIDENT_READ})


def test_the_legacy_api_prefix_enforces_the_same_permissions() -> None:
    table = _route_table()
    mirrors = {
        key: permissions
        for key, permissions in table.items()
        if key[1].startswith("/api/") and not key[1].startswith("/api/v1/") and _is_governed(key[1])
    }
    assert mirrors, "expected the legacy /api mirror to expose governed routes"

    for (method, path), permissions in mirrors.items():
        twin = (method, f"/api/v1{path[len('/api') :]}")
        assert twin in table, f"{method} {path} has no /api/v1 counterpart"
        assert permissions == table[twin], (
            f"{method} {path} enforces {sorted(permissions) or 'nothing'} "
            f"while {twin[1]} enforces {sorted(table[twin]) or 'nothing'}"
        )


def test_declared_permissions_come_from_the_vocabulary() -> None:
    vocabulary = set(ALL_PERMISSIONS)
    for (method, path), permissions in _route_table().items():
        unknown = permissions - vocabulary
        assert not unknown, f"{method} {path} requires undeclared permission(s): {sorted(unknown)}"
        assert WILDCARD not in permissions, (
            f"{method} {path} must name a permission, not the wildcard"
        )
