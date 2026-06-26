import struct
import time

from ..const import WEIGHT_KEY
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


def parse_weight(payload: bytearray) -> dict[str, int | float | None]:
    """
    Parse raw data received from the ESF-24 scale.

    Args:
        payload (bytearray): Raw data received from the scale.

    Returns:
        dict: Dictionary containing parsed data with the following keys:
            - "weight": Weight value in kilograms
    """
    data = dict[str, int | float | None]()
    weight = int(payload[3:5].hex(), 16)
    data[WEIGHT_KEY] = round(float(weight) / 100, 2)
    return data
