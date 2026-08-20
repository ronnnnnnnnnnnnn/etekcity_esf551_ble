"""Tests for advertisement-based model detection.

Fixtures are real captured payloads (manufacturer-data value as reported by
bleak/HA — the two-byte company ID already stripped).
"""

import logging

from src.etekcity_esf551_ble import detection as detection_module
from src.etekcity_esf551_ble.detection import (
    CAPABILITIES,
    ETEKCITY_MANUFACTURER_ID,
    QN_MANUFACTURER_ID,
    ScaleModel,
    detect_model,
    is_etekcity_frame,
    parse_model_code,
)

# Real captures
ESF551_PAYLOAD = bytes.fromhex("0162291c004dd00002")  # D0:4D:00:1C:29:62, code 2
FIT8S_PAYLOAD = bytes.fromhex("0163a0ed5d89a9c0a901563a0100000100020300")  # code 49321
PURIFIER_PAYLOAD = bytes.fromhex(
    "018e31e5519140c623020202"
)  # air purifier, code 0xC623
ESF24_PAYLOAD = bytes.fromhex("012601000607aa0b44ac04")  # QN frame, code 0x0126
ESF17_PAYLOAD = bytes.fromhex("00d30100005b0d1cfefefe")  # QN frame, code 0x00D3
RENPHO_QN_PAYLOAD = bytes.fromhex(
    "09e900000003aa670003ff"
)  # foreign QN scale, code 0x09E9
# Synthetic: Etekcity frame for MAC CF:EA:01:28:86:45 with code 5
EFSA591S_PAYLOAD = bytes.fromhex("0145862801eacf0005")
EFSC651_PAYLOAD = bytes.fromhex("32469a1706e9cf0088030201")

MFR = ETEKCITY_MANUFACTURER_ID
QN = QN_MANUFACTURER_ID


def test_manufacturer_id_constants():
    assert ETEKCITY_MANUFACTURER_ID == 1744
    assert QN_MANUFACTURER_ID == 65535


def test_scale_model_values_are_stable():
    # These string values are persisted in HA config entries — never change them.
    assert ScaleModel.ESF551.value == "ESF-551"
    assert ScaleModel.ESF24.value == "ESF-24"
    assert ScaleModel.FIT8S.value == "FIT-8S"
    assert ScaleModel.EFSA591S.value == "EFS-A591S"
    assert ScaleModel.EFSC651.value == "EFS-C651"
    assert ScaleModel.ESF17.value == "ESF-17"
    assert ScaleModel.ESF18.value == "ESF-18"


def test_parse_model_code_reads_be16_at_offset_7():
    assert parse_model_code(ESF551_PAYLOAD) == 2
    assert parse_model_code(FIT8S_PAYLOAD) == 49321
    assert parse_model_code(PURIFIER_PAYLOAD) == 0xC623
    assert parse_model_code(EFSA591S_PAYLOAD) == 5
    assert parse_model_code(EFSC651_PAYLOAD) == 136


def test_registry_covers_known_variants():
    # Every registered regional/hardware variant resolves on its identifier
    # alone, without needing a name or address fallback. The MAC deliberately
    # matches no OUI matcher, so a code missing from the registry fails here
    # instead of being rescued by a fallback.
    mac = "AA:BB:CC:11:22:33"
    reversed_mac = bytes(int(o, 16) for o in mac.split(":"))[::-1]
    expected = {
        (ScaleModel.ESF551, MFR): (1, 2),
        (ScaleModel.EFSA591S, MFR): (3, 5, 127, 134),
        (ScaleModel.FIT8S, MFR): (49321,),
        (ScaleModel.ESF24, QN): (294, 946),
        (ScaleModel.ESF17, QN): (211,),
        (ScaleModel.ESF18, QN): (671,),
    }
    for (model, mfr_id), codes in expected.items():
        for code in codes:
            if mfr_id == MFR:
                payload = b"\x01" + reversed_mac + code.to_bytes(2, "big")
            else:
                payload = code.to_bytes(2, "big") + b"\x01\x00\x06" + reversed_mac
            assert detect_model(None, {mfr_id: payload}, address=mac) == model, code


def test_parse_model_code_rejects_short_payloads():
    assert parse_model_code(b"") is None
    assert parse_model_code(bytes.fromhex("0162291c004dd000")) is None  # 8 bytes


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


def test_detect_efsc651_real_capture():
    assert (
        detect_model(
            "Etekcity Smart Fitness Scale",
            {MFR: EFSC651_PAYLOAD},
            address="CF:E9:06:17:9A:46",
        )
        == ScaleModel.EFSC651
    )


def test_detect_efsc651_without_address():
    assert (
        detect_model("Etekcity Smart Fitness Scale", {MFR: EFSC651_PAYLOAD})
        == ScaleModel.EFSC651
    )


def test_detect_efsc651_with_corebluetooth_address():
    assert (
        detect_model(
            "Etekcity Smart Fitness Scale",
            {MFR: EFSC651_PAYLOAD},
            address="AF727D4C-932A-D465-3F2C-A6640868DE71",
        )
        == ScaleModel.EFSC651
    )


def test_efsc651_variable_header_requires_matching_mac():
    assert (
        detect_model(None, {MFR: EFSC651_PAYLOAD}, address="AA:BB:CC:DD:EE:FF") is None
    )


def test_efsc651_wrong_mac_does_not_fallback_to_esf551_name():
    assert (
        detect_model(
            "Etekcity Smart Fitness Scale",
            {MFR: EFSC651_PAYLOAD},
            address="AA:BB:CC:DD:EE:FF",
        )
        is None
    )


def test_detect_fit8s_by_model_code():
    assert detect_model(None, {MFR: FIT8S_PAYLOAD}) == ScaleModel.FIT8S


def test_detect_esf24_by_qn_model_code():
    # No name needed: QN frame + MAC echo identifies it.
    assert (
        detect_model(None, {QN: ESF24_PAYLOAD}, address="04:AC:44:0B:AA:07")
        == ScaleModel.ESF24
    )


def test_qn_frame_requires_mac_echo():
    # Same payload but a different device address: reject (65535 is a
    # catch-all company ID, the MAC echo is the trust anchor).
    assert detect_model(None, {QN: ESF24_PAYLOAD}, address="AA:BB:CC:DD:EE:FF") is None


def test_foreign_qn_scale_rejected():
    # A non-Etekcity QingNiu scale: name doesn't match "QN-Scale1" and its
    # model identifier (0x09E9) is not in the registry.
    assert (
        detect_model("QN-Scale", {QN: RENPHO_QN_PAYLOAD}, address="FF:03:00:67:AA:03")
        is None
    )


def test_detect_esf24_by_name_without_mfr_data():
    # The ESF-17 advertises the same name, so without manufacturer data the
    # name alone cannot separate the two — the fallback deliberately reports
    # ESF-24 (protocol-identical; only the reported model name differs).
    assert detect_model("QN-Scale1", {}) == ScaleModel.ESF24
    assert detect_model("QN-Scale1", None) == ScaleModel.ESF24


def test_detect_esf17_real_capture():
    # Issue #43 capture: QN frame code 0x00D3 (211), MAC FE:FE:FE:1C:0D:5B.
    assert (
        detect_model("QN-Scale1", {QN: ESF17_PAYLOAD}, address="FE:FE:FE:1C:0D:5B")
        == ScaleModel.ESF17
    )


def test_detect_esf17_passive_no_name():
    # The registered code alone identifies it; the shared QN-Scale1 name
    # fallback (which would say ESF-24) must not be consulted.
    assert (
        detect_model(None, {QN: ESF17_PAYLOAD}, address="FE:FE:FE:1C:0D:5B")
        == ScaleModel.ESF17
    )


def test_esf17_frame_requires_mac_echo_when_address_given():
    assert (
        detect_model("QN-Scale1", {QN: ESF17_PAYLOAD}, address="AA:BB:CC:DD:EE:FF")
        == ScaleModel.ESF24
    )
    # Without the name there is nothing left to match on.
    assert detect_model(None, {QN: ESF17_PAYLOAD}, address="AA:BB:CC:DD:EE:FF") is None


def test_rejects_non_scale_1744_device():
    # Air purifier: same company ID, identifier 0xC623.
    assert detect_model("Core200s", {MFR: PURIFIER_PAYLOAD}) is None


def test_address_prefix_fallback_when_code_unreadable():
    # Truncated mfr data: code unreadable, but 1744 present + known OUI.
    assert (
        detect_model(None, {MFR: b"\x01\x45"}, address="CF:EA:01:28:86:45")
        == ScaleModel.EFSA591S
    )


def test_oui_matcher_outranks_shared_name():
    # Three models advertise "Etekcity Smart Fitness Scale"; when the code
    # is unreadable, a model-specific OUI must win over the shared name.
    shared_name = "Etekcity Smart Fitness Scale"
    for address, model in (
        ("CF:EA:01:28:86:45", ScaleModel.EFSA591S),
        ("CF:E9:06:17:9A:46", ScaleModel.EFSC651),
        ("A9:89:5D:ED:A0:63", ScaleModel.FIT8S),
        ("D0:4D:00:1C:29:62", ScaleModel.ESF551),
    ):
        assert (
            detect_model(shared_name, {MFR: b"\x01\x45"}, address=address) == model
        ), address


def test_shared_name_resolves_by_generation():
    # No OUI hit and no usable identifier: the header generation is the only
    # remaining signal. Generation 2 → EFS-C651 (the only gen-2 scale);
    # generation 1 → None, because the ESF-551 and EFS-A591S cannot be told
    # apart and a wrong guess configures a silently broken protocol.
    shared_name = "Etekcity Smart Fitness Scale"
    assert (
        detect_model(shared_name, {MFR: b"\x32\x45"}, address="AA:BB:CC:DD:EE:FF")
        == ScaleModel.EFSC651
    )
    assert (
        detect_model(shared_name, {MFR: b"\x01\x45"}, address="AA:BB:CC:DD:EE:FF")
        is None
    )
    # The motivating real-world case: a passive/truncated EFS-C651 frame on
    # macOS, where the address is an opaque CoreBluetooth UUID and no OUI
    # matcher can ever fire.
    assert (
        detect_model(
            shared_name,
            {MFR: b"\x32\x45"},
            address="AF727D4C-932A-D465-3F2C-A6640868DE71",
        )
        == ScaleModel.EFSC651
    )
    # An empty 1744 payload has no readable generation: stay unclassified.
    assert detect_model(shared_name, {MFR: b""}) is None


def test_address_prefix_requires_manufacturer_id():
    # A known OUI without the required manufacturer ID must not match.
    assert detect_model(None, {}, address="CF:EA:01:28:86:45") is None


def test_unknown_device_returns_none():
    assert detect_model("SomeHeadphones", {76: b"\x02\x15" + b"\x00" * 20}) is None
    assert detect_model(None, None) is None


def test_qn_frame_dynamic_bytes_ignored():
    # Same ESF-24 unit, different bytes 3-4 across captures (issue #11):
    # the identifier at bytes 0-1 and the MAC echo are all that matter.
    # Byte 4 is the scale's pending stored-record count, so it varies with
    # the device's state rather than being noise.
    for h in ("012601010107aa0b44ac04", "012601000207aa0b44ac04"):
        assert (
            detect_model(None, {QN: bytes.fromhex(h)}, address="04:AC:44:0B:AA:07")
            == ScaleModel.ESF24
        )


def test_unrecognized_variant_logs_identifier(caplog):
    # Generation-1 frame with an identifier not in the registry and only the
    # shared name: unclassifiable (ESF-551 vs EFS-A591S), but the identifier
    # must still be logged so the registry can be extended.
    detection_module._reported_identifiers.clear()
    # Identifier 4 is not assigned to any known model, so it stays a safe
    # stand-in for an unregistered variant.
    payload = bytes.fromhex("0162291c004dd00004")
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        assert detect_model("Etekcity Smart Fitness Scale", {MFR: payload}) is None
    assert "unrecognized model identifier 4" in caplog.text


def test_unregistered_gen2_variant_resolves_to_efsc651(caplog):
    # A hypothetical EFS-C651 sibling: generation-2 frame,
    # valid MAC echo, unregistered identifier, shared name. The MAC matches
    # no OUI matcher, so only the header generation identifies the family;
    # the identifier is logged for reporting.
    detection_module._reported_identifiers.clear()
    payload = bytes.fromhex("32332211ccbbaa0089")  # identifier 137
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        assert (
            detect_model(
                "Etekcity Smart Fitness Scale",
                {MFR: payload},
                address="AA:BB:CC:11:22:33",
            )
            == ScaleModel.EFSC651
        )
    assert "unrecognized model identifier 137" in caplog.text


def test_is_etekcity_frame():
    # Any Etekcity-platform frame qualifies, scale or not (platform check,
    # not a scale check) — unknown future models must never be filtered out.
    assert is_etekcity_frame(ESF551_PAYLOAD, "D0:4D:00:1C:29:62")
    assert is_etekcity_frame(PURIFIER_PAYLOAD, "40:91:51:E5:31:8E")
    # Generation-2 frame (EFS-C651, header 0x32): the header's upper bits
    # are state flags, only the generation nibble is structural.
    assert is_etekcity_frame(EFSC651_PAYLOAD, "CF:E9:06:17:9A:46")
    # Unknown-model frame with a MAC/identifier we've never seen: still
    # recognized as platform traffic.
    assert is_etekcity_frame(bytes.fromhex("01be213329e74800b1"))
    # MAC-echo mismatch or wrong shape: rejected.
    assert not is_etekcity_frame(ESF551_PAYLOAD, "AA:BB:CC:DD:EE:FF")
    assert not is_etekcity_frame(EFSC651_PAYLOAD, "AA:BB:CC:DD:EE:FF")
    assert not is_etekcity_frame(RENPHO_QN_PAYLOAD, "FF:03:00:67:AA:03")
    assert not is_etekcity_frame(b"\x01\x62")
    # Unknown generation nibble: layout can't be trusted.
    assert not is_etekcity_frame(b"\x03" + ESF551_PAYLOAD[1:], "D0:4D:00:1C:29:62")


def test_efsc651_header_flag_variants_accepted():
    # The generation-2 header carries flags in its upper bits (0x32
    # captured; bit 7 toggles with device state, so 0xB2 is the same scale
    # in another state). All must classify on the model code + MAC echo.
    for header in (0x32, 0xB2, 0x12, 0x22, 0x02):
        payload = bytes([header]) + EFSC651_PAYLOAD[1:]
        assert (
            detect_model(None, {MFR: payload}, address="CF:E9:06:17:9A:46")
            == ScaleModel.EFSC651
        ), hex(header)


def test_etekcity_registry_requires_frame_shape():
    # Registered identifier but an unknown generation nibble: not trusted.
    bad_header = b"\x03" + ESF551_PAYLOAD[1:]
    assert detect_model(None, {MFR: bad_header}) is None
    # Registered identifier but MAC echo mismatching the device address.
    assert (
        detect_model(None, {MFR: ESF551_PAYLOAD}, address="AA:BB:CC:DD:EE:FF") is None
    )
    # Same payload with the matching address still detects.
    assert (
        detect_model(None, {MFR: ESF551_PAYLOAD}, address="D0:4D:00:1C:29:62")
        == ScaleModel.ESF551
    )


def test_qn_frame_without_address_accepts_registered_code():
    # Without an address there is no echo to check; the registry still gates.
    assert detect_model(None, {QN: ESF24_PAYLOAD}) == ScaleModel.ESF24
    assert detect_model(None, {QN: RENPHO_QN_PAYLOAD}) is None


def test_name_matching_is_case_insensitive():
    assert detect_model("qn-scale1", {}) == ScaleModel.ESF24
    # Shared-name handling must be case-insensitive too (gen-2 → EFS-C651).
    assert (
        detect_model("ETEKCITY SMART FITNESS SCALE", {MFR: b"\x32\x62"})
        == ScaleModel.EFSC651
    )


def test_invalid_frame_identifier_not_reported(caplog):
    # Unregistered identifier on a frame whose MAC echo fails: the name
    # matcher may still classify the device, but the please-report warning
    # must not cite a code read off an untrusted payload.
    detection_module._reported_identifiers.clear()
    payload = bytes.fromhex("0162291c004dd00063")  # identifier 99, ESF-551 MAC
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        assert (
            detect_model(
                "Etekcity Smart Fitness Scale",
                {MFR: payload},
                address="AA:BB:CC:DD:EE:FF",
            )
            is None
        )
    assert "unrecognized model identifier" not in caplog.text


def test_unrecognized_identifier_logged_once(caplog):
    detection_module._reported_identifiers.clear()
    payload = bytes.fromhex("0162291c004dd00063")  # identifier 99
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        detect_model("Etekcity Smart Fitness Scale", {MFR: payload})
        detect_model("Etekcity Smart Fitness Scale", {MFR: payload})
    assert caplog.text.count("unrecognized model identifier 99") == 1


def test_every_model_has_capabilities():
    assert set(CAPABILITIES) == set(ScaleModel)


def test_capability_flags():
    assert CAPABILITIES[ScaleModel.ESF24].has_impedance is True
    assert CAPABILITIES[ScaleModel.ESF17].has_impedance is True
    assert CAPABILITIES[ScaleModel.ESF17].display_unit_settable is True
    assert CAPABILITIES[ScaleModel.ESF18].has_impedance is True
    assert CAPABILITIES[ScaleModel.ESF18].display_unit_settable is True
    assert CAPABILITIES[ScaleModel.ESF551].has_impedance is True
    assert CAPABILITIES[ScaleModel.FIT8S].has_impedance is True
    assert CAPABILITIES[ScaleModel.EFSA591S].has_impedance is True
    assert CAPABILITIES[ScaleModel.EFSC651].has_impedance is True
    # Heart rate: EFS-A591S only
    assert [m for m in ScaleModel if CAPABILITIES[m].has_heart_rate] == [
        ScaleModel.EFSA591S
    ]
    # FIT-8S display unit is observed-only (advertisement scale, no GATT write)
    assert CAPABILITIES[ScaleModel.FIT8S].display_unit_settable is False


def test_public_api_exports():
    import src.etekcity_esf551_ble as lib

    assert lib.ScaleModel is ScaleModel
    assert lib.detect_model is detect_model
    assert lib.CAPABILITIES is CAPABILITIES
    # SCALE_CLASSES maps every model to its client class
    assert set(lib.SCALE_CLASSES) == set(ScaleModel)
    assert lib.SCALE_CLASSES[ScaleModel.EFSA591S] is lib.EFSA591SScale
    assert lib.SCALE_CLASSES[ScaleModel.EFSC651] is lib.EFSC651Scale
    assert lib.SCALE_CLASSES[ScaleModel.ESF551] is lib.ESF551Scale
    assert lib.SCALE_CLASSES[ScaleModel.ESF24] is lib.ESF24Scale
    assert lib.SCALE_CLASSES[ScaleModel.FIT8S] is lib.FIT8SScale
    assert lib.SCALE_CLASSES[ScaleModel.ESF17] is lib.ESF24Scale
    assert lib.SCALE_CLASSES[ScaleModel.ESF18] is lib.ESF24Scale
    assert "SCALE_CLASSES" in lib.__all__
    for name in lib.__all__:
        assert hasattr(lib, name), f"__all__ exports missing attribute: {name}"


def test_unrecognized_qn_identifier_logged(caplog):
    # Symmetric with the Etekcity family: a QN-frame device that a fallback
    # matcher still identifies gets its unknown identifier logged too.
    detection_module._reported_identifiers.clear()
    # Synthetic QN frame: identifier 0x0226 (not in the registry), with a MAC
    # echo matching the address below so it clears the trust anchor.
    payload = bytes.fromhex("022602000065b30b44ac04")
    with caplog.at_level(logging.INFO, logger="src.etekcity_esf551_ble.detection"):
        assert (
            detect_model(None, {QN: payload}, address="04:AC:44:0B:B3:65")
            == ScaleModel.ESF24
        )
        detect_model(None, {QN: payload}, address="04:AC:44:0B:B3:65")
    assert caplog.text.count("unrecognized model identifier 550") == 1
