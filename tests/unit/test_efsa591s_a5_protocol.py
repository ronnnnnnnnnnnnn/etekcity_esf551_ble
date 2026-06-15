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

from src.etekcity_esf551_ble.efsa591s import a5_protocol as p

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
            frames.extend(r.feed(MEAS[i:i + 20]))
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
