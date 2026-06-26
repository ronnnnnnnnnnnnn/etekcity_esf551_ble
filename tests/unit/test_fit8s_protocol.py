"""Unit tests for parsing functions (FIT8S)."""

import pytest

from src.etekcity_esf551_ble.fit8s.protocol import parse
from src.etekcity_esf551_ble.const import DISPLAY_UNIT_KEY, IMPEDANCE_KEY, WEIGHT_KEY

ADDRESS = "A9:89:5D:ED:A0:63"

# Wireshark sample: weight=80470g=80.47kg, no impedance, display=KG, stable
SAMPLE_KG = bytearray.fromhex("0163a0ed5d89a9c0a901563a0100000100020300")

# Live capture: weight=81020g=81.02kg, impedance=537 ohms, display=KG, stable
SAMPLE_KG_WITH_IMPEDANCE = bytearray.fromhex("0163a0ed5d89a9c0a9017c3c0119020100020300")

# Synthetic stable packets for LB and ST (byte 16 changed, byte 15 forced to 0x01)
SAMPLE_LB = bytearray.fromhex("0163a0ed5d89a9c0a901563a0100000101020300")
SAMPLE_ST = bytearray.fromhex("0163a0ed5d89a9c0a901563a0100000102020300")


def test_parse():
    """Test FIT8S parsing function."""
    # Stable reading without impedance, KG
    result = parse(SAMPLE_KG, ADDRESS)
    assert result is not None
    assert result[WEIGHT_KEY] == pytest.approx(80.47)
    assert result[DISPLAY_UNIT_KEY] == 0  # WeightUnit.KG
    assert IMPEDANCE_KEY not in result

    # Stable reading with impedance, KG
    result = parse(SAMPLE_KG_WITH_IMPEDANCE, ADDRESS)
    assert result is not None
    assert result[WEIGHT_KEY] == pytest.approx(81.02)
    assert result[DISPLAY_UNIT_KEY] == 0  # WeightUnit.KG
    assert result[IMPEDANCE_KEY] == 537

    # LB display unit
    result = parse(SAMPLE_LB, ADDRESS)
    assert result is not None
    assert result[DISPLAY_UNIT_KEY] == 1  # WeightUnit.LB

    # ST display unit
    result = parse(SAMPLE_ST, ADDRESS)
    assert result is not None
    assert result[DISPLAY_UNIT_KEY] == 2  # WeightUnit.ST

    # Address validation skipped when not provided
    result = parse(SAMPLE_KG)
    assert result is not None
    assert result[WEIGHT_KEY] == pytest.approx(80.47)

    # Invalid length
    assert parse(SAMPLE_KG[:-1], ADDRESS) is None
    assert parse(SAMPLE_KG + b"\x00", ADDRESS) is None

    # Wrong MAC
    wrong_mac = bytearray(SAMPLE_KG)
    wrong_mac[3] ^= 0xFF
    assert parse(wrong_mac, ADDRESS) is None

    # Unstable reading
    unstable = bytearray(SAMPLE_KG)
    unstable[15] = 0x00
    assert parse(unstable, ADDRESS) is None
