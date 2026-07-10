"""Tests for advertisement-based model detection.

Fixtures are real captured payloads (manufacturer-data value as reported by
bleak/HA — the two-byte company ID already stripped).
"""

from src.etekcity_esf551_ble.detection import (
    ETEKCITY_MANUFACTURER_ID,
    QN_MANUFACTURER_ID,
    ScaleModel,
    parse_model_code,
)

# Real captures
ESF551_PAYLOAD = bytes.fromhex("0162291c004dd00002")  # D0:4D:00:1C:29:62, code 2
FIT8S_PAYLOAD = bytes.fromhex("0163a0ed5d89a9c0a901563a0100000100020300")  # code 49321
PURIFIER_PAYLOAD = bytes.fromhex("018e31e5519140c623020202")  # air purifier, code 0xC623
ESF24_PAYLOAD = bytes.fromhex("01260100069ea50b44ac04")  # QN frame, code 9729
RENPHO_QN_PAYLOAD = bytes.fromhex("09e9000000230a670003ff")  # foreign QN scale, code 0xE900
# Synthetic: Etekcity frame for MAC CF:EA:01:28:86:45 with code 5
EFSA591S_PAYLOAD = bytes.fromhex("0145862801eacf0005")


def test_manufacturer_id_constants():
    assert ETEKCITY_MANUFACTURER_ID == 1744
    assert QN_MANUFACTURER_ID == 65535


def test_scale_model_values_are_stable():
    # These string values are persisted in HA config entries — never change them.
    assert ScaleModel.ESF551.value == "ESF-551"
    assert ScaleModel.ESF24.value == "ESF-24"
    assert ScaleModel.FIT8S.value == "FIT-8S"
    assert ScaleModel.EFSA591S.value == "EFS-A591S"


def test_parse_model_code_reads_be16_at_offset_7():
    assert parse_model_code(ESF551_PAYLOAD) == 2
    assert parse_model_code(FIT8S_PAYLOAD) == 49321
    assert parse_model_code(PURIFIER_PAYLOAD) == 0xC623
    assert parse_model_code(EFSA591S_PAYLOAD) == 5


def test_parse_model_code_rejects_short_payloads():
    assert parse_model_code(b"") is None
    assert parse_model_code(bytes.fromhex("0162291c004dd000")) is None  # 8 bytes
