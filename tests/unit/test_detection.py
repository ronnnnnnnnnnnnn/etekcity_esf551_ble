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


from src.etekcity_esf551_ble.detection import detect_model  # noqa: E402

MFR = ETEKCITY_MANUFACTURER_ID
QN = QN_MANUFACTURER_ID


def test_detect_esf551_by_model_code():
    assert (
        detect_model("Etekcity Smart Fitness Scale", {MFR: ESF551_PAYLOAD})
        == ScaleModel.ESF551
    )


def test_detect_efsa591s_by_code_despite_esf551_name():
    # Active scan: the EFS-A591S reports the ESF-551's name; the code must win.
    assert (
        detect_model("Etekcity Smart Fitness Scale", {MFR: EFSA591S_PAYLOAD})
        == ScaleModel.EFSA591S
    )


def test_detect_efsa591s_passive_no_name():
    assert detect_model(None, {MFR: EFSA591S_PAYLOAD}) == ScaleModel.EFSA591S


def test_detect_fit8s_by_model_code():
    assert detect_model(None, {MFR: FIT8S_PAYLOAD}) == ScaleModel.FIT8S


def test_detect_esf24_by_qn_model_code():
    # No name needed: QN frame + MAC echo identifies it.
    assert (
        detect_model(None, {QN: ESF24_PAYLOAD}, address="04:AC:44:0B:A5:9E")
        == ScaleModel.ESF24
    )


def test_qn_frame_requires_mac_echo():
    # Same payload but a different device address: reject (65535 is a
    # catch-all company ID, the MAC echo is the trust anchor).
    assert detect_model(None, {QN: ESF24_PAYLOAD}, address="AA:BB:CC:DD:EE:FF") is None


def test_foreign_qn_scale_rejected():
    # A non-Etekcity QingNiu scale: name doesn't match "QN-Scale1" and its
    # model identifier (0xE900) is not in the registry.
    assert (
        detect_model("QN-Scale", {QN: RENPHO_QN_PAYLOAD}, address="FF:03:00:67:0A:23")
        is None
    )


def test_detect_esf24_by_name_without_mfr_data():
    assert detect_model("QN-Scale1", {}) == ScaleModel.ESF24
    assert detect_model("QN-Scale1", None) == ScaleModel.ESF24


def test_rejects_non_scale_1744_device():
    # Air purifier: same company ID, identifier 0xC623.
    assert detect_model("Core200s", {MFR: PURIFIER_PAYLOAD}) is None


def test_address_prefix_fallback_when_code_unreadable():
    # Truncated mfr data: code unreadable, but 1744 present + known OUI.
    assert (
        detect_model(None, {MFR: b"\x01\x45"}, address="CF:EA:01:28:86:45")
        == ScaleModel.EFSA591S
    )


def test_address_prefix_requires_manufacturer_id():
    # A known OUI without the required manufacturer ID must not match.
    assert detect_model(None, {}, address="CF:EA:01:28:86:45") is None


def test_unknown_device_returns_none():
    assert detect_model("SomeHeadphones", {76: b"\x02\x15" + b"\x00" * 20}) is None
    assert detect_model(None, None) is None


def test_qn_frame_dynamic_bytes_ignored():
    # Same ESF-24 unit, different bytes 3-4 across captures (issue #11):
    # the identifier at bytes 1-2 and the MAC echo are all that matter.
    for h in ("01260101019ea50b44ac04", "01260100029ea50b44ac04"):
        assert (
            detect_model(None, {QN: bytes.fromhex(h)}, address="04:AC:44:0B:A5:9E")
            == ScaleModel.ESF24
        )


def test_unrecognized_variant_logs_identifier(caplog):
    # ESF-551-style frame with an identifier not in the registry: the name
    # matcher still detects it, and the identifier is logged for reporting.
    import logging

    payload = bytes.fromhex("0162291c004dd00001")  # identifier 1
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        assert (
            detect_model("Etekcity Smart Fitness Scale", {MFR: payload})
            == ScaleModel.ESF551
        )
    assert "unrecognized model identifier 1" in caplog.text


def test_is_etekcity_frame():
    from src.etekcity_esf551_ble.detection import is_etekcity_frame

    # Any Etekcity-platform frame qualifies, scale or not (platform check,
    # not a scale check) — unknown future models must never be filtered out.
    assert is_etekcity_frame(ESF551_PAYLOAD, "D0:4D:00:1C:29:62")
    assert is_etekcity_frame(PURIFIER_PAYLOAD, "40:91:51:E5:31:8E")
    # Unknown-model frame with a MAC/identifier we've never seen: still
    # recognized as platform traffic.
    assert is_etekcity_frame(bytes.fromhex("01be213329e74800b1"))
    # MAC-echo mismatch or wrong shape: rejected.
    assert not is_etekcity_frame(ESF551_PAYLOAD, "AA:BB:CC:DD:EE:FF")
    assert not is_etekcity_frame(RENPHO_QN_PAYLOAD, "FF:03:00:67:0A:23")
    assert not is_etekcity_frame(b"\x01\x62")
