import struct
import time
from typing import NamedTuple

from ..const import IMPEDANCE_500KHZ_KEY, IMPEDANCE_KEY, WEIGHT_KEY
from ..data import WeightUnit

CMD_SET_DISPLAY_UNIT = bytearray.fromhex("1309150010283700a0")
CMD_END_MEASUREMENT = bytearray.fromhex("1f05151049")
_EPOCH_OFFSET = 946656000


def build_unit_update_command(desired_unit: WeightUnit) -> bytearray:
    """
    Build the unit update command for ESF24.

    Args:
        desired_unit: The desired weight unit (0=kg, 1=lb, 2=st)

    Returns:
        bytearray: The payload to send to the scale to update the display unit
    """
    payload = CMD_SET_DISPLAY_UNIT.copy()
    payload[3] &= 0xF0
    payload[8] &= 0xF0
    if desired_unit == WeightUnit.KG:
        payload[3] |= 1
        payload[8] |= 1
    elif desired_unit == WeightUnit.LB:
        payload[3] |= 2
        payload[8] |= 2
    elif desired_unit == WeightUnit.ST:
        payload[3] |= 8
        payload[8] |= 8
    return payload


def build_measurement_initiation_command() -> bytearray:
    """Return a fresh measurement initiation command with current timestamp and checksum."""
    cmd = bytearray(8)
    cmd[0:3] = b"\x20\x08\x15"
    ts = int(time.time()) - _EPOCH_OFFSET
    struct.pack_into("<I", cmd, 3, ts)
    cmd[7] = sum(cmd[0:7]) & 0xFF
    return cmd


_MEASUREMENT_FRAME_PREFIX = b"\x10\x0b\x15"
_MEASUREMENT_FRAME_LENGTH = 11
_STATUS_FINAL = 0x01


def is_measurement_frame(payload: bytearray) -> bool:
    """
    Return True if the payload is an ESF-24 measurement frame.

    Every frame of a weigh-in matches, not just the final one: the scale
    streams the weight while it settles and the BIA runs. Only the final
    frame carries a usable reading — see :func:`parse_weight`.
    """
    return (
        len(payload) == _MEASUREMENT_FRAME_LENGTH
        and payload[0:3] == _MEASUREMENT_FRAME_PREFIX
    )


def parse_weight(payload: bytearray) -> dict[str, int | float | None] | None:
    """
    Parse a measurement frame received from the ESF-24 scale.

    Args:
        payload (bytearray): Raw data received from the scale.

    Returns:
        dict: Dictionary containing parsed data with the following keys:
            - "weight": Weight value in kilograms
            - "impedance": 50 kHz impedance in ohms (omitted when not measured)
            - "impedance_500khz": 500 kHz impedance in ohms (same rules)

    Returns None unless the payload is a final ESF-24 measurement frame: a
    settling frame carries no usable reading, and other QingNiu scales emit
    0x10 frame variants with different field offsets.
    """
    if not is_measurement_frame(payload) or payload[5] != _STATUS_FINAL:
        return None
    data = dict[str, int | float | None]()
    weight = int.from_bytes(payload[3:5], "big")
    data[WEIGHT_KEY] = round(float(weight) / 100, 2)
    # Resistances read 0 when the scale did not measure them. VeSync consumes
    # them raw (the QN resistance bit-swap is advertisement-gated, never on
    # for the ESF-24).
    if resistance_1 := int.from_bytes(payload[6:8], "big"):
        data[IMPEDANCE_KEY] = resistance_1
    if resistance_2 := int.from_bytes(payload[8:10], "big"):
        data[IMPEDANCE_500KHZ_KEY] = resistance_2
    return data


# --- Stored offline measurements (22 04 query / 23 14 records) --------------

_STORED_MEASUREMENT_FRAME_PREFIX = b"\x23\x14\x15"
_STORED_MEASUREMENT_FRAME_LENGTH = 20


def build_stored_measurement_query() -> bytearray:
    """Build the stored-measurement query (``22 04 15`` + checksum).

    The scale answers with one 0x23 record per offline reading (or a
    single ``count=0`` frame when the store is empty) — see
    :func:`parse_stored_measurement`. Delivering a record deletes it from
    the scale's store; there is no separate delete command.
    """
    cmd = bytearray(b"\x22\x04\x15")
    cmd.append(sum(cmd) & 0xFF)
    return cmd


def is_stored_measurement_frame(payload: bytearray) -> bool:
    """Return True if the payload is an ESF-24 stored-measurement record.

    The ESF-24 record is 20 bytes (length byte 0x14); the otherwise
    identical renpho QN record is 19 (0x13), so the exact-length match
    also keeps that variant out.
    """
    return (
        len(payload) == _STORED_MEASUREMENT_FRAME_LENGTH
        and payload[0:3] == _STORED_MEASUREMENT_FRAME_PREFIX
    )


class _StoredFrame(NamedTuple):
    """Decoded stored offline-measurement record fields."""

    count: int
    index: int
    timestamp: int
    weight_kg: float
    resistance_1: int
    resistance_2: int

    @property
    def measurements(self) -> dict[str, int | float | None]:
        """The record as a measurements dict, keyed like :func:`parse_weight`.

        Applies the same "0 means not measured" rule: a resistance band
        the scale did not measure is omitted rather than reported as 0.
        """
        data = dict[str, int | float | None]()
        data[WEIGHT_KEY] = self.weight_kg
        if self.resistance_1:
            data[IMPEDANCE_KEY] = self.resistance_1
        if self.resistance_2:
            data[IMPEDANCE_500KHZ_KEY] = self.resistance_2
        return data


def parse_stored_measurement(payload: bytearray) -> _StoredFrame | None:
    """Decode a stored offline-measurement record.

    The scale sends one record per offline reading in response to the
    query. Layout::

        0..2    prefix 23 14 15
        3       count — total records in this batch (0 = store empty)
        4       index — 1-based position of this record in the batch
        5..8    timestamp, little-endian uint32, seconds since
                2000-01-01 00:00:00 UTC
        9..10   weight, big-endian uint16, 0.01 kg
        11..12  resistance 1 (50 kHz)
        13..14  resistance 2 (500 kHz)
        15..18  reserved (0x00)
        19      checksum, mod-256 sum of bytes 0..18

    ``timestamp`` is returned as unix seconds. When ``count == 0`` the
    store is empty and the remaining fields are meaningless — callers
    must not read them.

    Returns None unless the payload is a stored-measurement frame with a
    valid trailing checksum.
    """
    if not is_stored_measurement_frame(payload):
        return None
    if payload[-1] != sum(payload[:-1]) & 0xFF:
        return None
    return _StoredFrame(
        count=payload[3],
        index=payload[4],
        timestamp=int.from_bytes(payload[5:9], "little") + _EPOCH_OFFSET,
        weight_kg=round(int.from_bytes(payload[9:11], "big") / 100, 2),
        resistance_1=int.from_bytes(payload[11:13], "big"),
        resistance_2=int.from_bytes(payload[13:15], "big"),
    )
