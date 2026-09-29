"""Shared fixtures for the top-level backend test modules.

The PostgreSQL harness lives in ``tests/incidents/conftest.py`` and is scoped to
that package. Rather than duplicate it, or re-export its fixtures from a module
namespace (which reads as a redefinition to the linter), the fixtures are
imported here so pytest exposes them to every test under ``tests/`` including
the sibling Phase 7.1-A context tests.

The harness stays opt-in: without ``ALARM_TEST_DATABASE_URL`` it skips, so a run
with no PostgreSQL still passes.
"""

from __future__ import annotations

from tests.incidents.conftest import (  # noqa: F401  (fixtures re-exported)
    db_engine,
    provisioned_database,
    session,
    sessions,
    test_database_url,
)
