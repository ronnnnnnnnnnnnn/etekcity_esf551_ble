"""Unit tests for the ESF-37 protocol helpers.

Frames are real captured bytes from a btsnoop session with a physical
ESF-37 (2026-08-15), spanning ten weigh-ins from 14.5 kg to 120.2 kg.
"""

from unittest.mock import patch

from src.etekcity_esf551_ble.esf37.protocol import (
    build_frame,
    build_init_command,
    build_time_sync_command,
    is_measurement_frame,
    parse_weight,
)


def test_build_frame_matches_capture():
    # Real init command captured from the vendor app.
    assert build_frame(0xC0, bytes([0x02])).hex() == "feefc0a3c00102c3"


def test_build_time_sync_command():
    fixed = 1_786_798_000
    with patch("src.etekcity_esf551_ble.esf37.protocol.time.time", return_value=fixed):
        cmd = build_time_sync_command()
    assert cmd.hex().startswith("feefc0a3c604")
    assert int.from_bytes(cmd[6:10], "big") == fixed
    assert cmd[-1] == sum(cmd[4:-1]) & 0xFF


def test_build_init_command_matches_capture():
    assert build_init_command().hex() == "feefc0a3c00102c3"


def test_parse_weight_142lb_reading():
    # 10st 2lb = 142 lb exactly; decodes to 64.40 kg and 142.00 lb (both
    # fields agree with the display exactly, not just within rounding).
    frame = bytearray.fromhex("feefc0a3d0081928377801020000cb")
    data = parse_weight(frame)
    assert data == {"weight": 64.40}


def test_parse_weight_265lb_reading():
    # 18st 13lb = 265 lb exactly; same exact-match pattern as the 142lb case.
    frame = bytearray.fromhex("feefc0a3d0082ef4678401020000e8")
    data = parse_weight(frame)
    assert data == {"weight": 120.20}


def test_parse_weight_with_body_fat_percentage():
    # Real capture, live weigh-in (2026-08-17 17:19): 226 lb, app-displayed
    # body fat 35.5% for this household member -> byte 13 decodes to 35
    # (truncated, not rounded -- only one ground-truth reading confirms
    # this so far, see the module docstring).
    frame = bytearray.fromhex("feefc0a3d008280a584801020223d2")
    data = parse_weight(frame)
    assert data == {"weight": 102.50, "body_fat_percentage": 35.0}


def test_parse_weight_omits_body_fat_percentage_without_bia_contact():
    # Same shape as the 142lb reading: BIA-complete byte (index 12) is
    # 0x00, so no body_fat_percentage key is added.
    frame = bytearray.fromhex("feefc0a3d0081928377801020000cb")
    data = parse_weight(frame)
    assert data == {"weight": 64.40}


def test_parse_weight_rejects_settling_frame():
    # Same frame as the 142lb reading above but with status=0x00: dozens of
    # these stream before the final one during a weigh-in.
    settling = bytearray.fromhex("feefc0a3d0081928377800020000ca")
    assert parse_weight(settling) is None


def test_parse_weight_rejects_bad_checksum():
    corrupted = bytearray.fromhex("feefc0a3d0081928377801020000ff")
    assert parse_weight(corrupted) is None


def test_is_measurement_frame():
    assert is_measurement_frame(bytearray.fromhex("feefc0a3d0081928377801020000cb"))
    assert is_measurement_frame(bytearray.fromhex("feefc0a3d0081928377800020000ca"))
    # A different command byte (ack frame) is not a measurement frame.
    assert not is_measurement_frame(bytearray.fromhex("feefc0a3db0101dd"))
    assert not is_measurement_frame(bytearray.fromhex("feefc0a3d008192837780102"))
