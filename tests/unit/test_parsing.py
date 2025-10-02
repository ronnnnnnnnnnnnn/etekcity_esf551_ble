"""Unit tests for parsing functions."""

from src.etekcity_esf551_ble.esf551.parser import parse as esf551_parse


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

