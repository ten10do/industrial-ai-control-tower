"""Incident transition table tests.

The expected matrix below is written from the phase specification, not from the
implementation, so a change to ``INCIDENT_TRANSITIONS`` cannot pass by silently
agreeing with itself.
"""

from __future__ import annotations

import pytest

from app.incidents.states import (
    INCIDENT_TRANSITIONS,
    OPEN_INCIDENT_STATUSES,
    TERMINAL_INCIDENT_STATUSES,
    IncidentStatus,
    as_incident_status,
    describe_incident_transitions,
    is_incident_transition_allowed,
    open_incident_status_values,
)

VALID: list[tuple[IncidentStatus, IncidentStatus]] = [
    # operator chain
    (IncidentStatus.OPEN, IncidentStatus.ACKNOWLEDGED),
    (IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING),
    (IncidentStatus.INVESTIGATING, IncidentStatus.MITIGATED),
    (IncidentStatus.MITIGATED, IncidentStatus.RESOLVED),
    (IncidentStatus.RESOLVED, IncidentStatus.CLOSED),
    (IncidentStatus.CLOSED, IncidentStatus.REOPENED),
    (IncidentStatus.REOPENED, IncidentStatus.INVESTIGATING),
    # cancellation
    (IncidentStatus.OPEN, IncidentStatus.CANCELLED),
    (IncidentStatus.ACKNOWLEDGED, IncidentStatus.CANCELLED),
    # workflow-owned edges (the engine writes these statuses with raw strings)
    (IncidentStatus.OPEN, IncidentStatus.UNDER_ANALYSIS),
    (IncidentStatus.ACKNOWLEDGED, IncidentStatus.UNDER_ANALYSIS),
    (IncidentStatus.INVESTIGATING, IncidentStatus.UNDER_ANALYSIS),
    (IncidentStatus.UNDER_ANALYSIS, IncidentStatus.ACTION_PENDING),
    (IncidentStatus.UNDER_ANALYSIS, IncidentStatus.MITIGATED),
    (IncidentStatus.ACTION_PENDING, IncidentStatus.WORK_ORDER_CREATED),
    (IncidentStatus.WORK_ORDER_CREATED, IncidentStatus.MITIGATED),
]

STATUSES = list(IncidentStatus)


def _expected_table() -> dict[IncidentStatus, frozenset[IncidentStatus]]:
    table: dict[IncidentStatus, frozenset[IncidentStatus]] = {
        status: frozenset() for status in STATUSES
    }
    for current, target in VALID:
        table[current] = table[current] | {target}
    return table


def test_the_table_declares_exactly_the_specified_moves() -> None:
    assert _expected_table() == INCIDENT_TRANSITIONS


def test_every_status_has_a_table_entry() -> None:
    assert set(INCIDENT_TRANSITIONS) == set(STATUSES)


@pytest.mark.parametrize(("current", "target"), VALID)
def test_declared_moves_are_allowed(current: IncidentStatus, target: IncidentStatus) -> None:
    assert is_incident_transition_allowed(current, target)


def test_closed_has_exactly_the_reopen_exit() -> None:
    assert INCIDENT_TRANSITIONS[IncidentStatus.CLOSED] == frozenset({IncidentStatus.REOPENED})


@pytest.mark.parametrize("current", STATUSES)
def test_only_cancelled_has_no_exit(current: IncidentStatus) -> None:
    if current is IncidentStatus.CANCELLED:
        assert INCIDENT_TRANSITIONS[current] == frozenset()
    else:
        assert len(INCIDENT_TRANSITIONS[current]) > 0


def test_terminality_is_exactly_closed_and_cancelled() -> None:
    assert (
        frozenset({IncidentStatus.CLOSED, IncidentStatus.CANCELLED}) == TERMINAL_INCIDENT_STATUSES
    )


def test_the_named_forbidden_moves_are_refused() -> None:
    assert not is_incident_transition_allowed(IncidentStatus.CLOSED, IncidentStatus.INVESTIGATING)
    assert not is_incident_transition_allowed(IncidentStatus.CANCELLED, IncidentStatus.OPEN)
    assert not is_incident_transition_allowed(IncidentStatus.OPEN, IncidentStatus.INVESTIGATING)
    assert not is_incident_transition_allowed(IncidentStatus.RESOLVED, IncidentStatus.MITIGATED)


def test_open_statuses_are_every_live_state() -> None:
    expected = {
        IncidentStatus.OPEN,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.INVESTIGATING,
        IncidentStatus.UNDER_ANALYSIS,
        IncidentStatus.ACTION_PENDING,
        IncidentStatus.WORK_ORDER_CREATED,
        IncidentStatus.MITIGATED,
        IncidentStatus.REOPENED,
    }
    assert expected == OPEN_INCIDENT_STATUSES


def test_open_status_values_are_plain_strings() -> None:
    values = open_incident_status_values()
    assert values == sorted(values)
    assert set(values) == {status.value for status in OPEN_INCIDENT_STATUSES}


def test_describe_transitions_sorts_for_stable_rendering() -> None:
    described = describe_incident_transitions(IncidentStatus.OPEN)
    assert described == sorted(described)
    assert set(described) == {"ACKNOWLEDGED", "CANCELLED", "UNDER_ANALYSIS"}


def test_as_incident_status_refuses_unknown_values() -> None:
    assert as_incident_status("OPEN") is IncidentStatus.OPEN
    with pytest.raises(ValueError):
        as_incident_status("SOMEWHERE_ELSE")
