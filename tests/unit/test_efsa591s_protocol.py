"""
Unit tests for the EFS-A591S A5 encrypted transport, validated against real
captured frames from a live measurement session.

Session-1 ground truth (recovered from captured frames):
    MAC      = CF:EA:01:28:86:45
    KE req   d=41983 e=31 f=9840  -> g=16
    KE resp  h=20670
    shared   = 20670**16 mod 41983 = 25182
    key      = ef10cd7eeb72a06dc93c5b51da301e11
    iv       = 09470abfaefc72cb9b5ab1ae0b865218  (from VERIFY frame)
"""

import struct

from src.etekcity_esf551_ble.efsa591s import protocol as p

MAC = "CF:EA:01:28:86:45"
REV_MAC = bytes.fromhex("45862801eacf")

KE_REQ = bytes.fromhex("a52314160088010142000055592f6af00645862801eacfffa31f7026")
KE_RESP = bytes.fromhex("a513140f001f0101420000000645862801eacfbe50")
VERIFY = bytes.fromhex(
    "a523152500860102420001f146fa4ff79667f73e080119110e0cddbfe3655b8794cb46664b14c9d9c73969"
)
MEAS = bytes.fromhex(
    "a5033825008a012144000150242bf17c291c80514cf20804c2b26a627dfa6324a2c9dd53c449d800add65c"
)

KEY = bytes.fromhex("ef10cd7eeb72a06dc93c5b51da301e11")
IV = bytes.fromhex("09470abfaefc72cb9b5ab1ae0b865218")
SHARED = 25182


class TestFraming:
    def test_checksum_total_is_ff(self):
        # every captured frame: sum of all bytes ≡ 0xFF (mod 256)
        for fr in (KE_REQ, KE_RESP, VERIFY, MEAS):
            assert sum(fr) % 256 == 0xFF

    def test_build_frame_matches_checksum(self):
        # rebuild the KE request body and confirm the checksum byte
        payload = KE_REQ[11:]
        frame = p.build_frame(0x14, p.OPCODE_KEY_EXCHANGE, payload, p.CHANNEL_PLAINTEXT)
        assert frame == KE_REQ

    def test_parse_frame(self):
        f = p.parse_frame(KE_REQ)
        assert f is not None
        assert f.opcode == p.OPCODE_KEY_EXCHANGE
        assert f.seq == 0x14
        assert f.channel == p.CHANNEL_PLAINTEXT
        assert f.payload == KE_REQ[11:]

    def test_parse_frame_rejects_bad(self):
        assert p.parse_frame(b"\x00\x01\x02") is None
        assert p.parse_frame(KE_REQ[:-1]) is None  # truncated

    def test_reassembler(self):
        r = p.FrameReassembler()
        # split MEAS into 20-byte chunks like BLE notifications
        frames = []
        for i in range(0, len(MEAS), 20):
            frames.extend(r.feed(MEAS[i : i + 20]))
        assert frames == [MEAS]


class TestMacAndDH:
    def test_reversed_mac(self):
        assert p.reversed_mac_bytes(MAC) == REV_MAC

    def test_dh_public_value(self):
        # f = e**g mod d
        assert pow(31, 16, 41983) == 9840

    def test_compute_shared(self):
        assert p.compute_shared(20670, 16, 41983) == SHARED

    def test_derive_key_matches_capture(self):
        assert p.derive_key(SHARED, MAC) == KEY

    def test_generate_dh_is_valid(self):
        dh = p.generate_dh()
        assert p.DH_MOD_MIN <= dh.d <= p.DH_MOD_MAX
        assert p.DH_BASE_MIN <= dh.e <= p.DH_BASE_MAX
        assert p.DH_EXP_MIN <= dh.g <= p.DH_EXP_MAX
        assert dh.f == pow(dh.e, dh.g, dh.d)


class TestKeyExchange:
    def test_parse_ke_response(self):
        assert p.parse_key_exchange_response(KE_RESP) == 20670

    def test_build_ke_request_roundtrip(self):
        dh = p.DHParams(d=41983, e=31, g=16, f=9840)
        frame = p.build_key_exchange(0x14, MAC, dh)
        parsed = p.parse_frame(frame)
        assert parsed.opcode == p.OPCODE_KEY_EXCHANGE
        pl = parsed.payload
        assert pl[5] == 6 and pl[6:12] == REV_MAC
        assert struct.unpack("<H", pl[12:14])[0] == 41983
        assert pl[14] == 31
        assert struct.unpack("<H", pl[15:17])[0] == 9840


class TestVerifyAndDecrypt:
    def test_verify_frame_yields_iv(self):
        # decrypt the captured VERIFY with (key, zero-IV) and pull the IV
        parsed = p.parse_frame(VERIFY)
        pt = p.decrypt_frame_payload(KEY, bytes(16), parsed)
        assert pt[1:7] == REV_MAC
        assert pt[7] == 16
        assert pt[8:24] == IV

    def test_build_verify_roundtrip(self):
        frame = p.build_key_verify(0x15, MAC, IV, KEY)
        parsed = p.parse_frame(frame)
        assert parsed.opcode == p.OPCODE_KEY_VERIFY
        assert parsed.channel == p.CHANNEL_AES
        pt = p.decrypt_frame_payload(KEY, bytes(16), parsed)
        assert pt[1:7] == REV_MAC
        assert pt[8:24] == IV

    def test_decrypt_measurement(self):
        parsed = p.parse_frame(MEAS)
        pt = p.decrypt_frame_payload(KEY, IV, parsed)
        m = p.parse_measurement(pt)
        assert m is not None
        # session-1 first live frame: weight is grams (uint24 LE) / 1000
        assert m.weight_kg == 11.2
        assert m.impedance is None
        assert m.final is False


class TestResultFrame:
    # decrypted 0x443a final-result frame (round 3 key): weight 111.25 kg, imp 424
    RESULT_PT = bytes.fromhex(
        "32323239313131325f5f5f5f5f5f5f5f5f5f5f5f000092b201a801000080592f6a0101015803"
    )

    def test_parse_result(self):
        m = p.parse_result(self.RESULT_PT)
        assert m is not None
        assert m.weight_kg == 111.25
        assert m.impedance == 424
        assert m.final is True
        assert m.heart_rate == 88  # byte[36] = 0x58
        assert m.display_unit == 1  # byte[35] = 0x01 = lb (capture was in lb)

    def test_parse_result_display_unit_mapping(self):
        # byte[35] encodes the scale's display unit: 0=kg, 1=lb, 2=st; other => None
        # (confirmed by kg-vs-lb capture diff: byte[35] flips 1->0, bytes 33/34 constant)
        for raw, expected in ((0, 0), (1, 1), (2, 2), (7, None)):
            pt = bytearray(self.RESULT_PT)
            pt[35] = raw
            assert p.parse_result(bytes(pt)).display_unit == expected

    def test_parse_result_heart_rate_zero_is_none(self):
        # byte[36] == 0 means HR not measured (stepped off early / not barefoot)
        pt = bytearray(self.RESULT_PT)
        pt[36] = 0
        m = p.parse_result(bytes(pt))
        assert m is not None
        assert m.heart_rate is None


class TestPlaintextOpcodes:
    """
    Captured from a live Etekcity_Apex (EFS-A591S) session where the scale
    never answered KEY_EXCHANGE and streamed unencrypted 0x4121 / 0x413C
    frames instead (HA issue #41, MAC 34:94:54:F1:F8:76 via ESPHome proxy).
    """

    LIVE = bytes.fromhex("a5020712003401214100981502000042d6756a0001010000")
    # Final result: serial "7992861_", weight 136.60 kg, impedance 0
    RESULT = bytes.fromhex(
        "a5020e2700a8013c4100373939323836315f5f5f5f5f5f5f5f5f5f5f5f5f"
        "0000981502000049d6756a01010100"
    )
    # Step-off live frame (weight 0) after the result
    LIVE_ZERO = bytes.fromhex("a502101200bc0121410000000000005ad6756a0000000008")

    def test_live_opcode_and_weight(self):
        parsed = p.parse_frame(self.LIVE)
        assert parsed is not None
        assert parsed.opcode == p.OPCODE_MEASUREMENT_PLAIN
        pt = p.plain_payload(parsed)
        m = p.parse_measurement(pt)
        assert m is not None
        assert m.weight_kg == 136.6
        assert m.final is False
        assert m.impedance is None

    def test_result_opcode_and_weight(self):
        parsed = p.parse_frame(self.RESULT)
        assert parsed is not None
        assert parsed.opcode == p.OPCODE_RESULT_PLAIN
        pt = p.plain_payload(parsed)
        m = p.parse_result_plain(pt)
        assert m is not None
        assert m.weight_kg == 136.6
        assert m.final is True
        # Impedance field is zero on this capture (stepped off / no BIA lock)
        assert m.impedance is None
        # Serial / name region starts with the ASCII device id
        assert pt[0:7] == b"7992861"
        # The plaintext layout carries the display unit two bytes earlier than
        # the encrypted frame (byte[33], not [35]); this capture was in lb.
        assert m.display_unit == 1
        # No heart rate on this capture (byte[34] == 0).
        assert m.heart_rate is None

    def test_plaintext_result_layout_differs_from_encrypted(self):
        # Reusing the encrypted parser would still get weight and impedance
        # (same offsets) but would misread the display unit off the frame's end.
        pt = p.plain_payload(p.parse_frame(self.RESULT))
        plain = p.parse_result_plain(pt)
        encrypted_layout = p.parse_result(pt)
        assert plain.weight_kg == encrypted_layout.weight_kg  # 136.6, shared
        assert plain.display_unit == 1  # recovered
        assert encrypted_layout.display_unit is None  # byte[35] is off the end

    # Two barefoot weigh-ins on a physical EFS-A591S-KUS, contributed by
    # @gthelding (PR #12), with the heart rate cross-checked against the BPM on
    # the scale's own display. Unlike RESULT above (socks on, so impedance and
    # HR both zero), these carry a real BIA impedance and pulse — the first
    # plaintext frames that exercise the full result decode. Values are the
    # reassembled payloads (as returned by plain_payload).
    BAREFOOT_RESULTS = (
        # payload, weight_kg, impedance, heart_rate
        (
            "373939323836315f5f5f5f5f5f5f5f5f5f5f5f5f0000021502ef00d4107b6a01010162",
            136.45,
            239,
            98,
        ),
        (
            "373939323836315f5f5f5f5f5f5f5f5f5f5f5f5f0000541802ee00be117b6a0101013a",
            137.3,
            238,
            58,
        ),
    )

    def test_barefoot_result_impedance_and_heart_rate(self):
        for hex_pt, weight, impedance, heart_rate in self.BAREFOOT_RESULTS:
            m = p.parse_result_plain(bytes.fromhex(hex_pt))
            assert m is not None, hex_pt
            assert m.final is True
            assert m.weight_kg == weight
            assert m.impedance == impedance
            assert m.heart_rate == heart_rate  # byte[34], matches the scale display
            assert m.display_unit == 1  # lb

    def test_live_zero_weight_is_parseable(self):
        parsed = p.parse_frame(self.LIVE_ZERO)
        assert parsed is not None
        assert parsed.opcode == p.OPCODE_MEASUREMENT_PLAIN
        m = p.parse_measurement(p.plain_payload(parsed))
        assert m is not None
        assert m.weight_kg == 0.0

    def test_plain_payload_reassembles_channel_byte(self):
        parsed = p.parse_frame(self.LIVE)
        # Without reassembly, the first weight byte is misread as "channel"
        assert parsed.channel == 0x98
        pt = p.plain_payload(parsed)
        assert pt[0] == 0x98
        assert pt[1:3] == bytes.fromhex("1502")


class TestSetUnit:
    # Ground truth captured from the app (Frida): channel-1 session key/iv and the
    # exact ciphertext the app's AES doFinal produced for each unit's 0xa163 write.
    KEY = bytes.fromhex("c7780d30ff1e531cd89258386b4b9b0b")
    IV = bytes.fromhex("bdbd7f418b52652c4fc29552736b1051")
    CIPHERTEXT = {
        0: "7b31dfe6f1db7baf68402299cbd934c0",  # kg
        1: "2f8010a5274df10d308c1544cda350c5",  # lb
        2: "6e06d4ad2e18dda2c0791628258cec91",  # st
    }
    # Full lb frame at seq 0x03 captured verbatim from the app's FFF2 write
    # (validates flags + checksum + framing end to end).
    LB_FRAME = "a523031500a90163a100012f8010a5274df10d308c1544cda350c5"

    def test_build_set_unit_ciphertext_matches_app(self):
        for unit, ct in self.CIPHERTEXT.items():
            parsed = p.parse_frame(p.build_set_unit(0x03, unit, self.KEY, self.IV))
            assert parsed.opcode == p.OPCODE_SET_UNIT
            assert parsed.channel == p.CHANNEL_AES
            assert parsed.payload.hex() == ct

    def test_build_set_unit_full_frame_matches_capture(self):
        assert p.build_set_unit(0x03, 1, self.KEY, self.IV).hex() == self.LB_FRAME

    def test_build_set_unit_rejects_invalid_unit(self):
        import pytest

        with pytest.raises(ValueError):
            p.build_set_unit(0x03, 5, self.KEY, self.IV)
