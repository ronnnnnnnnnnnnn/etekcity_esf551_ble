"""Unit tests for parsing functions."""

from src.etekcity_esf551_ble.esf551.protocol import parse as esf551_parse


def test_parse():
    """Test ESF-551 parsing function."""
    # Test valid data with impedance
    valid_data_with_impedance = bytearray(
        b"\xa5\x02\x00\x10\x00\x00\x01\x61\xa1\x00\xe8\x03\x00\x64\x00\x00\x00\x00\x00\x01\x01\x00"
    )
    result = esf551_parse(valid_data_with_impedance)
    assert result is not None
    assert result["weight"] == 1.0
    assert result["impedance"] == 100
    assert result["display_unit"] == 0

    # Test valid data without impedance
    valid_data_without_impedance = bytearray(
        b"\xa5\x02\x00\x10\x00\x00\x01\x61\xa1\x00\xe8\x03\x00\x64\x00\x00\x00\x00\x00\x01\x00\x00"
    )
    result = esf551_parse(valid_data_without_impedance)
    assert result is not None
    assert result["weight"] == 1.0
    assert "impedance" not in result
    assert result["display_unit"] == 0

    # Test invalid data
    invalid_data = bytearray(b"\x00" * 22)
    result = esf551_parse(invalid_data)
    assert result is None

    # Test invalid length
    invalid_length = bytearray(
        b"\xa5\x02\x00\x10\x00\x00\x01\x61\xa1\x00\xe8\x03\x00\x64\x00\x00\x00\x00\x00\x01\x01"
    )
    result = esf551_parse(invalid_length)
    assert result is None


_LIVE_FRAME = bytearray.fromhex("a502cc10004d0161a1000c1b0100003d2d3267000100")
_FINAL_FRAME = bytearray.fromhex("a502cd1000490161a1000c1b0100003f2d3267010100")


def test_is_esf551_frame_accepts_live_and_final_frames():
    from src.etekcity_esf551_ble.esf551.protocol import is_esf551_frame

    assert is_esf551_frame(_LIVE_FRAME) is True
    assert is_esf551_frame(_FINAL_FRAME) is True


def test_is_esf551_frame_rejects_foreign_or_short_payloads():
    from src.etekcity_esf551_ble.esf551.protocol import is_esf551_frame

    assert is_esf551_frame(bytearray(22)) is False
    assert is_esf551_frame(_FINAL_FRAME[:21]) is False
    assert is_esf551_frame(None) is False


def test_parse_returns_none_for_live_frame():
    assert esf551_parse(_LIVE_FRAME) is None
    assert esf551_parse(_FINAL_FRAME) == {"display_unit": 0, "weight": 72.46}
