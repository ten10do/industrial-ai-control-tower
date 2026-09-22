"""Deterministic holding-register definitions for the Modbus simulator."""

DEVICE_ID = 1
FIRST_HOLDING_REGISTER = 40001

REGISTER_VALUES: dict[int, int] = {
    40001: 685,
    40002: 1240,
    40003: 710,
    40004: 1480,
    40005: 720,
}


def holding_register_values() -> list[int]:
    """Return contiguous raw values beginning at holding register 40001."""

    return [REGISTER_VALUES[address] for address in sorted(REGISTER_VALUES)]
