"""EFS-C651-specific decoding layered on the shared encrypted A5 protocol."""

from __future__ import annotations

from ..efsa591s import protocol as a5

_IMPEDANCE_OFFSET = 25
_IMPEDANCE_MASK = 0x3FFFFF
_IMPEDANCE_NUMERATOR = 1 << 31
_MIN_IMPEDANCE_OHMS = 100
_MAX_IMPEDANCE_OHMS = 2000


def decode_impedance(plaintext: bytes) -> int | None:
    """Decode the C651 reciprocal fixed-point BIA field into whole ohms."""
    if len(plaintext) < _IMPEDANCE_OFFSET + 3:
        return None
    packed = (
        int.from_bytes(plaintext[_IMPEDANCE_OFFSET : _IMPEDANCE_OFFSET + 3], "little")
        & _IMPEDANCE_MASK
    )
    if packed == 0:
        return None
    impedance = round(_IMPEDANCE_NUMERATOR / packed)
    if not _MIN_IMPEDANCE_OHMS <= impedance <= _MAX_IMPEDANCE_OHMS:
        return None
    return impedance


def parse_result(plaintext: bytes) -> a5.Measurement | None:
    """Parse a C651 0x4422 result and replace its packed BIA field."""
    measurement = a5.parse_result(plaintext)
    if measurement is None:
        return None
    return measurement._replace(impedance=decode_impedance(plaintext), heart_rate=None)
