"""Unit tests for the ESF-24 protocol helpers."""

from unittest.mock import patch

import pytest

from src.etekcity_esf551_ble.esf24.protocol import (
    _EPOCH_OFFSET,
    build_measurement_initiation_command,
    build_stored_measurement_query,
    build_unit_update_command,
    is_measurement_frame,
    is_stored_measurement_frame,
    parse_stored_measurement,
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


# --- Stored offline measurements (22 04 query / 23 14 records) -------------
#
# All frames below are real captured bytes from vendor-app sessions with an
# ESF-24 (btsnoop capture, 2026-08-02 analysis). The scale answers the query
# with one 0x23 record per offline reading; delivering a record deletes it
# from the scale's store.


def test_build_stored_measurement_query_matches_capture():
    cmd = build_stored_measurement_query()
    assert cmd.hex() == "2204153b"
    assert cmd[-1] == sum(cmd[:-1]) & 0xFF


@pytest.mark.parametrize(
    "hx,count,index,ts_raw,weight,r1,r2",
    [
        # A six-record batch drained in one session...
        ("2314150601013d5b302bb60000000000000000fd", 6, 1, 0x305B3D01, 111.90, 0, 0),
        ("231415060232a15c3002d0000000000000000085", 6, 2, 0x305CA132, 7.20, 0, 0),
        ("231415060387105e3002b200000000000000002e", 6, 3, 0x305E1087, 6.90, 0, 0),
        ("231415060443836a3002c600000000000000007e", 6, 4, 0x306A8343, 7.10, 0, 0),
        ("231415060509806e3002cb00000000000000004b", 6, 5, 0x306E8009, 7.15, 0, 0),
        ("2314150606b9eb6e3002300000000000000000cc", 6, 6, 0x306EEBB9, 5.60, 0, 0),
        # ...and a single-record store with a full BIA reading.
        ("23141501016e6e73302b48016b013400000000e1", 1, 1, 0x30736E6E, 110.80, 363, 308),
    ],
)
def test_parse_stored_measurement_decodes_captured_records(
    hx, count, index, ts_raw, weight, r1, r2
):
    frame = parse_stored_measurement(bytearray.fromhex(hx))
    assert frame.count == count
    assert frame.index == index
    assert frame.timestamp == ts_raw + _EPOCH_OFFSET
    assert frame.weight_kg == weight
    assert frame.resistance_1 == r1
    assert frame.resistance_2 == r2


def test_parse_stored_measurement_empty_store():
    """count=0 means the store is empty; the other fields are meaningless."""
    frame = parse_stored_measurement(
        bytearray.fromhex("231415000000000000000000000000000000004c")
    )
    assert frame.count == 0


def test_stored_record_measurements_match_live_final_frame():
    # The core correctness check: the stored record and the live final frame
    # from the same capture session describe the same reading, so they must
    # decode to the same measurements (110.80 kg, 363 ohm, 308 ohm).
    stored = parse_stored_measurement(
        bytearray.fromhex("23141501016e6e73302b48016b013400000000e1")
    )
    live = parse_weight(bytearray.fromhex("100b152b4801016b013445"))
    assert stored.measurements == live


def test_stored_record_measurements_omit_unmeasured_resistances():
    # Same "0 means not measured" rule as parse_weight: the batch records
    # were taken without a BIA pass, so only weight is reported.
    frame = parse_stored_measurement(
        bytearray.fromhex("2314150601013d5b302bb60000000000000000fd")
    )
    assert frame.measurements == {"weight": 111.90}


def test_parse_stored_measurement_rejects_bad_checksum():
    good = bytearray.fromhex("23141501016e6e73302b48016b013400000000e1")
    assert parse_stored_measurement(good) is not None

    bad_trailer = good.copy()
    bad_trailer[-1] ^= 0xFF
    assert parse_stored_measurement(bad_trailer) is None

    # A corrupted body byte invalidates the trailing sum just the same.
    bad_body = good.copy()
    bad_body[9] ^= 0x01
    assert parse_stored_measurement(bad_body) is None


def test_parse_stored_measurement_rejects_non_stored_frames():
    # A live measurement frame, a truncated record, and renpho's 19-byte
    # (len=0x13) record shape are all rejected outright.
    assert parse_stored_measurement(bytearray.fromhex("100b152b4801016b013445")) is None
    assert parse_stored_measurement(bytearray.fromhex("23141501016e6e7330")) is None
    assert (
        parse_stored_measurement(
            bytearray.fromhex("2313ff04015dcdb6311cd901fc01f00000002e")
        )
        is None
    )


def test_is_stored_measurement_frame():
    assert is_stored_measurement_frame(
        bytearray.fromhex("23141501016e6e73302b48016b013400000000e1")
    )
    # count=0 (empty store) is still a stored-measurement frame.
    assert is_stored_measurement_frame(
        bytearray.fromhex("231415000000000000000000000000000000004c")
    )
    assert not is_stored_measurement_frame(bytearray.fromhex("100b152b4801016b013445"))
    assert not is_stored_measurement_frame(bytearray.fromhex("23141501016e6e7330"))
    assert not is_stored_measurement_frame(
        bytearray.fromhex("2313ff04015dcdb6311cd901fc01f00000002e")
    )


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
