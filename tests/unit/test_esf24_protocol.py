"""Unit tests for the ESF-24 protocol helpers."""

from unittest.mock import patch

from src.etekcity_esf551_ble.esf24.protocol import (
    _EPOCH_OFFSET,
    build_measurement_initiation_command,
    build_unit_update_command,
    is_measurement_frame,
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
    with patch("src.etekcity_esf551_ble.esf24.protocol.time.time", return_value=fixed):
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


def test_parse_weight_final_frame_surfaces_both_impedances():
    # Capture-verified final frame: weight 0x2b48 = 11080 -> 110.80 kg,
    # r1 (50 kHz) = 0x016b = 363, r2 (500 kHz) = 0x0134 = 308, raw big-endian.
    payload = bytearray.fromhex("100b152b4801016b013445")
    data = parse_weight(payload)
    assert data["weight"] == 110.80
    assert data["impedance"] == 363
    assert data["impedance_500khz"] == 308


def test_is_measurement_frame():
    # Recognizes every ESF-24 measurement frame, final or not, so the handler
    # can tell "measurement in progress" from a payload it knows nothing about.
    assert is_measurement_frame(bytearray.fromhex("100b152b4801016b013445"))
    assert is_measurement_frame(bytearray.fromhex("100b152b4800016b013445"))
    # Other QN variants, and the ESF-24's own non-measurement frames, are not.
    assert not is_measurement_frame(bytearray.fromhex("100e1504540100016b0134000045"))
    assert not is_measurement_frame(bytearray.fromhex("140b150000000000000000"))
    assert not is_measurement_frame(bytearray.fromhex("120f15000000000000000000000000"))


def test_parse_weight_rejects_settling_frame():
    # Only the final (status 0x01) frame carries a usable reading, so the
    # parser is the single place that decides what counts as one.
    assert parse_weight(bytearray.fromhex("100b152b4800016b013445")) is None


def test_parse_weight_omits_unmeasured_resistances_per_value():
    # A resistance of 0 means the scale did not measure it. Each band is
    # checked independently, so one can be reported without the other.
    zero_r2 = bytearray.fromhex("100b152b4801016b000045")
    data = parse_weight(zero_r2)
    assert data["impedance"] == 363
    assert "impedance_500khz" not in data

    zero_r1 = bytearray.fromhex("100b152b48010000013445")
    data = parse_weight(zero_r1)
    assert "impedance" not in data
    assert data["impedance_500khz"] == 308


def test_parsed_frame_feeds_body_metrics():
    # The documented ESF-24 body-composition flow: parse the final frame,
    # then hand weight + 50 kHz impedance to the standalone BodyMetrics.
    from src.etekcity_esf551_ble.body_metrics import BodyMetrics, Sex
    from src.etekcity_esf551_ble.const import IMPEDANCE_KEY, WEIGHT_KEY

    data = parse_weight(bytearray.fromhex("100b152b4801016b013445"))
    metrics = BodyMetrics(
        weight_kg=data[WEIGHT_KEY],
        height_m=1.85,
        age=40,
        sex=Sex.Male,
        impedance=data[IMPEDANCE_KEY],
    )
    assert 5 <= metrics.body_fat_percentage <= 75
    assert metrics.basal_metabolic_rate > 900


def test_parse_weight_rejects_other_qn_frame_variants():
    # An ES-30M flavor of the 0x10 frame is 14 bytes, carries weight in tenths
    # and puts r1/r2 one byte later. This one means 110.8 kg / 363 / 308; read
    # at ESF-24 offsets it would come out as 11.08 kg / 1 / 27393, so the
    # length/prefix guard has to reject it outright.
    es30m_like = bytearray.fromhex("100e1504540100016b0134000045")
    assert len(es30m_like) == 14
    assert parse_weight(es30m_like) is None
    assert parse_weight(bytearray.fromhex("120b152b4801016b013445")) is None
    assert parse_weight(bytearray.fromhex("100b16")) is None
