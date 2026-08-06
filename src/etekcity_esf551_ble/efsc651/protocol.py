"""EFS-C651-specific decoding layered on the shared encrypted A5 protocol."""

from __future__ import annotations

from ..efsa591s import protocol as a5

_IMPEDANCE_OFFSET = 25
_IMPEDANCE_SIZE = 4

_NO_MEASUREMENT = 0xFFFFFF
_MIN_IMPEDANCE_OHMS = 200
_MAX_IMPEDANCE_OHMS = 1200


def decode_impedance(plaintext: bytes) -> int | None:
    """
    Decode the C651's encoded BIA field into whole ohms.

    Returns None when the frame is too short, when the scale reported no
    measurement, or when the decoded value falls outside the allowed range.
    """
    if len(plaintext) < _IMPEDANCE_OFFSET + _IMPEDANCE_SIZE:
        return None
    encoded = int.from_bytes(
        plaintext[_IMPEDANCE_OFFSET : _IMPEDANCE_OFFSET + _IMPEDANCE_SIZE], "little"
    )
    if (encoded & 0xFFFFFF) == _NO_MEASUREMENT:
        return None

    # Bit breakdown within 32-bit LE word:
    # d = byte 0 (bits 0..7)
    # b = byte 1 lower nibble (bits 8..11, unshifted)
    # a = byte 1 upper nibble (bits 12..15)
    # c = byte 2 (bits 16..23)
    a = (encoded & 0x00F000) >> 12
    b = encoded & 0x000F00
    c = (encoded & 0xFF0000) >> 16
    d = encoded & 0x0000FF
    total = b + c - a - 4 * d
    impedance = total // 2

    if not _MIN_IMPEDANCE_OHMS <= impedance <= _MAX_IMPEDANCE_OHMS:
        return None
    return impedance


def parse_result(plaintext: bytes) -> a5.Measurement | None:
    """Parse a C651 0x4422 result and replace its encoded BIA field."""
    measurement = a5.parse_result(plaintext)
    if measurement is None:
        return None
    return measurement._replace(impedance=decode_impedance(plaintext), heart_rate=None)
