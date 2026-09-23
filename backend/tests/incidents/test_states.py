"""Alarm status vocabulary and the guarded transition table.

The transition matrix is written out here in full rather than derived from the
implementation table, so the test states the intended contract independently. A
test that reads its expectations back out of the code it is testing cannot fail.
"""

from __future__ import annotations

import pytest

from app.incidents.states import (
    ALARM_TRANSITIONS,
    OPEN_ALARM_STATUSES,
    AlarmSeverity,
    AlarmStatus,
    as_alarm_status,
    describe_alarm_transitions,
    is_alarm_transition_allowed,
    open_alarm_status_values,
    severity_at_least,
)

#: The full 3 x 3 contract. ``True`` means the move is legal.
EXPECTED_MATRIX: dict[tuple[AlarmStatus, AlarmStatus], bool] = {
    (AlarmStatus.ACTIVE, AlarmStatus.ACTIVE): False,
    (AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED): True,
    (AlarmStatus.ACTIVE, AlarmStatus.CLEARED): True,
    (AlarmStatus.ACKNOWLEDGED, AlarmStatus.ACTIVE): True,
    (AlarmStatus.ACKNOWLEDGED, AlarmStatus.ACKNOWLEDGED): False,
    (AlarmStatus.ACKNOWLEDGED, AlarmStatus.CLEARED): True,
    (AlarmStatus.CLEARED, AlarmStatus.ACTIVE): False,
    (AlarmStatus.CLEARED, AlarmStatus.ACKNOWLEDGED): False,
    (AlarmStatus.CLEARED, AlarmStatus.CLEARED): False,
}


def test_transition_matrix_is_exhaustive_and_matches_the_declared_contract() -> None:
    """Every ordered pair of the three statuses is asserted, not sampled."""

    covered = set()
    for current in AlarmStatus:
        for target in AlarmStatus:
            expected = EXPECTED_MATRIX[(current, target)]
            assert is_alarm_transition_allowed(current, target) is expected, (
                f"{current.value} -> {target.value}"
            )
            covered.add((current, target))
    assert covered == set(EXPECTED_MATRIX)


def test_the_matrix_covers_every_declared_pair() -> None:
    assert set(EXPECTED_MATRIX) == {
        (current, target) for current in AlarmStatus for target in AlarmStatus
    }


def test_cleared_to_active_is_refused() -> None:
    """A recurrence opens a new instance rather than reopening a closed one."""

    assert not is_alarm_transition_allowed(AlarmStatus.CLEARED, AlarmStatus.ACTIVE)


def test_cleared_is_terminal() -> None:
    assert ALARM_TRANSITIONS[AlarmStatus.CLEARED] == frozenset()


def test_describe_transitions_lists_legal_targets_in_a_stable_order() -> None:
    assert describe_alarm_transitions(AlarmStatus.ACTIVE) == ["ACKNOWLEDGED", "CLEARED"]
    assert describe_alarm_transitions(AlarmStatus.ACKNOWLEDGED) == ["ACTIVE", "CLEARED"]
    assert describe_alarm_transitions(AlarmStatus.CLEARED) == []


def test_open_statuses_exclude_cleared() -> None:
    assert {AlarmStatus.ACTIVE, AlarmStatus.ACKNOWLEDGED} == OPEN_ALARM_STATUSES
    assert open_alarm_status_values() == ["ACKNOWLEDGED", "ACTIVE"]
    assert "CLEARED" not in open_alarm_status_values()


def test_as_alarm_status_accepts_the_three_declared_values() -> None:
    for status in AlarmStatus:
        assert as_alarm_status(status.value) is status


def test_as_alarm_status_refuses_an_undeclared_value() -> None:
    with pytest.raises(ValueError):
        as_alarm_status("SUPERSEDED")


@pytest.mark.parametrize(
    ("candidate", "floor", "expected"),
    [
        ("CRITICAL", AlarmSeverity.CRITICAL, True),
        ("CRITICAL", AlarmSeverity.WARNING, True),
        ("WARNING", AlarmSeverity.WARNING, True),
        ("WARNING", AlarmSeverity.MAJOR, False),
        ("INFO", AlarmSeverity.MINOR, False),
        (None, AlarmSeverity.INFO, False),
        ("UNMAPPED", AlarmSeverity.INFO, False),
    ],
)
def test_severity_at_least_is_ordered_and_fails_closed(
    candidate: str | None, floor: AlarmSeverity, expected: bool
) -> None:
    """An unknown or absent severity must never read as severe."""

    assert severity_at_least(candidate, floor) is expected
