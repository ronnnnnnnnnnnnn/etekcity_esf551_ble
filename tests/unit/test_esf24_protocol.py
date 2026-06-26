"""Unit tests for the ESF-24 protocol helpers."""

from unittest.mock import patch

from src.etekcity_esf551_ble.esf24.protocol import (
    _EPOCH_OFFSET,
    build_measurement_initiation_command,
    build_unit_update_command,
    parse_weight,
)
from src.etekcity_esf551_ble.data import WeightUnit


def test_build_unit_update_command():
    # The low nibble of bytes 3 and 8 encodes the unit (kg=1, lb=2, st=8);
    # the rest of the template command is left untouched.
    assert build_unit_update_command(WeightUnit.KG).hex() == "1309150110283700a1"
    assert build_unit_update_command(WeightUnit.LB).hex() == "1309150210283700a2"
    assert build_unit_update_command(WeightUnit.ST).hex() == "1309150810283700a8"


def test_build_measurement_initiation_command():
    fixed = 1_700_000_000
    with patch(
        "src.etekcity_esf551_ble.esf24.protocol.time.time", return_value=fixed
    ):
        cmd = build_measurement_initiation_command()

    assert len(cmd) == 8
    assert cmd[0:3] == b"\x20\x08\x15"
    # timestamp: seconds since the scale's epoch, little-endian uint32
    assert int.from_bytes(cmd[3:7], "little") == fixed - _EPOCH_OFFSET
    # final byte is a mod-256 checksum over the first 7 bytes
    assert cmd[7] == sum(cmd[0:7]) & 0xFF


def test_parse_weight():
    # bytes [3:5] big-endian = 0x2710 = 10000 -> 100.00 kg
    payload = bytearray(b"\x10\x0b\x15\x27\x10\x01\x00\x00\x00\x00\x00")
    assert parse_weight(payload)["weight"] == 100.0

    # bytes [3:5] big-endian = 0x1b90 = 7056 -> 70.56 kg
    payload = bytearray(b"\x10\x0b\x15\x1b\x90\x01\x00\x00\x00\x00\x00")
    assert parse_weight(payload)["weight"] == 70.56
