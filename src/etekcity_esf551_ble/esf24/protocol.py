import struct
import time
from typing import NamedTuple

from ..const import IMPEDANCE_500KHZ_KEY, IMPEDANCE_KEY, WEIGHT_KEY
from ..data import WeightUnit

CMD_SET_DISPLAY_UNIT = bytearray.fromhex("1309150010283700a0")
_EPOCH_OFFSET = 946656000

# Byte 2 of every frame, both directions, is a per-scale "scale type": the
# vendor decoders read it from the scale's 0x12 unit request and echo it in
# every command. The ESF-24 units seen before used 0x15; the library issue
# #17 unit uses 0xff, as Renpho's QN scales do. The handler captures it per
# session and passes it to the builders and frame matchers below.
_DEFAULT_VENDOR_BYTE = 0x15

_UNIT_REQUEST_OPCODE = 0x12
# The vendor decoders accept a 0x12 frame of any length from 10 bytes up; its
# length differs by firmware (15 bytes on the 0x15 units, 16 on issue #17's).
_UNIT_REQUEST_MIN_LENGTH = 10


def is_unit_request_frame(payload: bytearray) -> bool:
    """Return True if the payload is the scale's 0x12 unit request.

    The scale repeats it every ~200 ms until a unit command answers it, and
    starts a measurement only after that. Its byte 2 is the vendor byte
    every reply must echo.
    """
    return (
        len(payload) >= _UNIT_REQUEST_MIN_LENGTH
        and payload[0] == _UNIT_REQUEST_OPCODE
    )


def _with_checksum(cmd: bytearray) -> bytearray:
    """Append the mod-256 sum of the command's bytes."""
    cmd.append(sum(cmd) & 0xFF)
    return cmd


def build_unit_update_command(
    desired_unit: WeightUnit, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> bytearray:
    """
    Build the unit update command for ESF24.

    Args:
        desired_unit: The desired weight unit (0=kg, 1=lb, 2=st)
        vendor_byte: The scale's byte 2, echoed from its unit request

    Returns:
        bytearray: The payload to send to the scale to update the display unit
    """
    payload = CMD_SET_DISPLAY_UNIT[:-1]
    payload[2] = vendor_byte
    payload[3] &= 0xF0
    if desired_unit == WeightUnit.KG:
        payload[3] |= 1
    elif desired_unit == WeightUnit.LB:
        payload[3] |= 2
    elif desired_unit == WeightUnit.ST:
        payload[3] |= 8
    return _with_checksum(payload)


def build_measurement_initiation_command(
    vendor_byte: int = _DEFAULT_VENDOR_BYTE,
) -> bytearray:
    """Return a fresh measurement initiation command with current timestamp and checksum."""
    cmd = bytearray(7)
    cmd[0:3] = bytes((0x20, 0x08, vendor_byte))
    ts = int(time.time()) - _EPOCH_OFFSET
    struct.pack_into("<I", cmd, 3, ts)
    return _with_checksum(cmd)


_MEASUREMENT_INIT_REQUEST_OPCODE_AND_LENGTH = b"\x14\x0b"
_MEASUREMENT_INIT_REQUEST_MIN_LENGTH = 11


def is_measurement_init_request(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> bool:
    """Return True if the payload is the scale's 0x14 measurement-init request.

    Answered with the set-time command, which the scale acks before it
    streams a measurement. Every capture sends 11 bytes; like the 0x10
    frame, only the minimum length is bounded — the vendor decoder sends
    set-time on any 0x14 frame.
    """
    return (
        len(payload) >= _MEASUREMENT_INIT_REQUEST_MIN_LENGTH
        and payload[0:2] == _MEASUREMENT_INIT_REQUEST_OPCODE_AND_LENGTH
        and payload[2] == vendor_byte
    )


_SET_TIME_ACK_OPCODE = 0x21
_SET_TIME_ACK_WIRE_LENGTH = 5


def is_set_time_ack(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> bool:
    """Return True if the payload acks our set-time (0x20) command.

    Capture-verified in two shapes, both five bytes on the wire:
    ``21 05 15 01 3c`` on the 0x15 units and ``21 04 ff 01 25`` on the
    0xff units (length byte four, one short of the wire length). Either
    length byte is accepted from either vendor byte: the ESF-24 client
    is basic-flavor only, so the length byte selects nothing here.
    """
    return (
        len(payload) == _SET_TIME_ACK_WIRE_LENGTH
        and payload[0] == _SET_TIME_ACK_OPCODE
        and payload[1] in (0x04, 0x05)
        and payload[2] == vendor_byte
    )


def build_end_measurement_command(
    vendor_byte: int = _DEFAULT_VENDOR_BYTE,
) -> bytearray:
    """Build the end-measurement command (``1f 05 <vendor> 10`` + checksum).

    Without it the scale repeats its final frame about twice a second.
    """
    return _with_checksum(bytearray((0x1F, 0x05, vendor_byte, 0x10)))


_MEASUREMENT_FRAME_OPCODE_AND_LENGTH = b"\x10\x0b"
_MEASUREMENT_FRAME_MIN_LENGTH = 11
_STATUS_FINAL = 0x01


def is_measurement_frame(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> bool:
    """
    Return True if the payload is an ESF-24 measurement frame.

    Every frame of a weigh-in matches, not just the final one: the scale
    streams the weight while it settles and the BIA runs. Only the final
    frame carries a usable reading — see :func:`parse_weight`.

    The length byte (0x0b) selects the frame flavor, so it is part of the
    prefix; the wire length is only bounded below. The ESF-24 sends 11
    bytes, but a firmware variant sends 12 with the same length byte and
    field offsets (checksum last) — the vendor decoder reads this frame by
    offset and never checks its length either.
    """
    return (
        len(payload) >= _MEASUREMENT_FRAME_MIN_LENGTH
        and payload[0:2] == _MEASUREMENT_FRAME_OPCODE_AND_LENGTH
        and payload[2] == vendor_byte
    )


def parse_weight(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> dict[str, int | float | None] | None:
    """
    Parse a measurement frame received from the ESF-24 scale.

    Args:
        payload (bytearray): Raw data received from the scale.
        vendor_byte: The session's vendor byte (see ``is_unit_request_frame``).

    Returns:
        dict: Dictionary containing parsed data with the following keys:
            - "weight": Weight value in kilograms
            - "impedance": 50 kHz impedance in ohms (omitted when not measured)
            - "impedance_500khz": 500 kHz impedance in ohms (same rules)

    Returns None unless the payload is a final ESF-24 measurement frame: a
    settling frame carries no usable reading, and other QingNiu scales emit
    0x10 frame variants with different field offsets.
    """
    if (
        not is_measurement_frame(payload, vendor_byte)
        or payload[5] != _STATUS_FINAL
    ):
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


# --- Stored offline measurements (22 04 query / 23 <len> records) -----------

_STORED_MEASUREMENT_OPCODE = 0x23
_STORED_MEASUREMENT_FRAME_MIN_LENGTH = 16


def build_stored_measurement_query(
    vendor_byte: int = _DEFAULT_VENDOR_BYTE,
) -> bytearray:
    """Build the stored-measurement query (``22 04 <vendor>`` + checksum).

    The scale answers with one 0x23 record per offline reading (or a
    single ``count=0`` frame when the store is empty) — see
    :func:`parse_stored_measurement`. Delivering a record deletes it from
    the scale's store; there is no separate delete command.
    """
    return _with_checksum(bytearray((0x22, 0x04, vendor_byte)))


def is_stored_measurement_frame(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> bool:
    """Return True if the payload is an ESF-24 stored-measurement record.

    The ESF-24 record is 20 bytes (length byte 0x14, four reserved bytes);
    firmware variants send 16 (0x10, no reserved bytes) and, on the 0xff
    units, 19 (0x13, three reserved bytes). All carry the fields at the
    same offsets with the checksum last, so the length byte is required
    to match the wire length rather than a fixed value.
    """
    return (
        len(payload) >= _STORED_MEASUREMENT_FRAME_MIN_LENGTH
        and payload[0] == _STORED_MEASUREMENT_OPCODE
        and payload[1] == len(payload)
        and payload[2] == vendor_byte
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


def parse_stored_measurement(
    payload: bytearray, vendor_byte: int = _DEFAULT_VENDOR_BYTE
) -> _StoredFrame | None:
    """Decode a stored offline-measurement record.

    The scale sends one record per offline reading in response to the
    query. Layout::

        0..2    prefix 23 <len> <vendor byte>
        3       count — total records in this batch (0 = store empty)
        4       index — 1-based position of this record in the batch
        5..8    timestamp, little-endian uint32, seconds since
                2000-01-01 00:00:00 UTC
        9..10   weight, big-endian uint16, 0.01 kg
        11..12  resistance 1 (50 kHz)
        13..14  resistance 2 (500 kHz)
        15..    reserved (0x00; absent on the 16-byte variant)
        last    checksum, mod-256 sum of all preceding bytes

    ``timestamp`` is returned as unix seconds. When ``count == 0`` the
    store is empty and the remaining fields are meaningless — callers
    must not read them.

    Returns None unless the payload is a stored-measurement frame with a
    valid trailing checksum.
    """
    if not is_stored_measurement_frame(payload, vendor_byte):
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
