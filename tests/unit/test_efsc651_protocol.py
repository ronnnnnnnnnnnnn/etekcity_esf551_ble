"""
Tests for the EFS-C651 protocol layer.

Ground truth: two decrypted 0x4422 result frames captured from a real
EFS-C651 (PacketLogger, 2026-08-05), together with the body fat percentage
the vendor app displayed for the same measurement. Both frames decode to
physiologically normal impedances, and each reproduces the app's figure
through the vendor's own body-composition algorithm — which is what confirms
the encoded-impedance transform in ``efsc651.protocol`` is correct.

  A  male,   33 y, 175 cm, 74.35 kg, kg mode -> 488 ohm, app showed 22.1%
  B  female, 31 y, 175 cm, 60.70 kg, kg mode -> 528 ohm, app showed 26.9%
"""

from src.etekcity_esf551_ble.efsc651 import protocol as p

# Capture A: weight 74.35 kg, encoded BIA field 0x8736AD.
RESULT_A = bytes.fromhex(
    "32323635303933365f5f5f5f5f5f5f5f5f5f5f5f0000" "6e2201ad3687002ed8726a0102000002"
)
# Capture B: weight 60.70 kg, encoded BIA field 0x8D141B.
RESULT_B = bytes.fromhex(
    "32323635303933365f5f5f5f5f5f5f5f5f5f5f5f0100" "1ced001b148d00338d736a0102000002"
)


class TestDecodeImpedance:
    def test_capture_a(self):
        assert p.decode_impedance(RESULT_A) == 488

    def test_capture_b(self):
        assert p.decode_impedance(RESULT_B) == 528

    def test_no_measurement_sentinel(self):
        pt = bytearray(RESULT_A)
        pt[25:29] = (0xFFFFFF).to_bytes(4, "little")
        assert p.decode_impedance(bytes(pt)) is None

    def test_no_measurement_sentinel_with_padded_bytes(self):
        pt = bytearray(RESULT_A)
        pt[25:29] = b"\xff\xff\xff\xff"
        assert p.decode_impedance(bytes(pt)) is None

    def test_zero_field_is_rejected(self):
        """A weight-only reading leaves the field zeroed."""
        pt = bytearray(RESULT_A)
        pt[25:29] = bytes(4)
        assert p.decode_impedance(bytes(pt)) is None

    def test_below_vendor_range_is_rejected(self):
        # Decodes to 128 ohm, under the vendor's 200 ohm floor.
        pt = bytearray(RESULT_A)
        pt[25:29] = (0x000100).to_bytes(4, "little")
        assert p.decode_impedance(bytes(pt)) is None

    def test_short_frame(self):
        assert p.decode_impedance(RESULT_A[:26]) is None


class TestParseResult:
    def test_capture_a(self):
        m = p.parse_result(RESULT_A)
        assert m is not None
        assert m.weight_kg == 74.35
        assert m.impedance == 488
        assert m.display_unit == 0  # kg
        assert m.final is True

    def test_capture_b(self):
        m = p.parse_result(RESULT_B)
        assert m is not None
        assert m.weight_kg == 60.70
        assert m.impedance == 528
        assert m.display_unit == 0

    def test_heart_rate_always_none(self):
        """The C651 has no heart-rate hardware; byte 36 is not a bpm value."""
        assert p.parse_result(RESULT_A).heart_rate is None
        assert p.parse_result(RESULT_B).heart_rate is None
