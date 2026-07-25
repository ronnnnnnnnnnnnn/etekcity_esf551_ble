import struct
import time

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
