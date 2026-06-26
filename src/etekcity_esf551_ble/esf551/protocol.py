import struct

from ..const import DISPLAY_UNIT_KEY, IMPEDANCE_KEY, WEIGHT_KEY

UNIT_UPDATE_COMMAND = bytearray.fromhex("a522030500000163a10000")


def parse(payload: bytearray) -> dict[str, int | float | None]:
    """
    Parse raw data received from the ESF-551 scale.

    Args:
        payload (bytearray): Raw data received from the scale.

    Returns:
        dict: Dictionary containing parsed data with the following keys:
            - "display_unit": Current display unit (0=kg, 1=lb, 2=st)
            - "weight": Weight value in kilograms
            - "impedance": Bioelectrical impedance value (if available)

    Returns None if the payload format is invalid or unrecognized.
    """
    if (
        payload is not None
        and len(payload) == 22
        and payload[19] == 1
        and payload[0:2] == b"\xa5\x02"
        and payload[3:5] == b"\x10\x00"
        and payload[6:10] == b"\x01\x61\xa1\x00"
    ):
        data = dict[str, int | float | None]()
        weight = struct.unpack("<I", payload[10:13].ljust(4, b"\x00"))[0]
        impedance = struct.unpack("<H", payload[13:15])[0]
        data[DISPLAY_UNIT_KEY] = int(payload[21])
        data[WEIGHT_KEY] = round(float(weight) / 1000, 2)
        if payload[20] == 1:
            if impedance := struct.unpack("<H", payload[13:15])[0]:
                data[IMPEDANCE_KEY] = int(impedance)
        return data
    return None


def build_unit_update_payload(desired_unit: int) -> bytearray:
    """
    Build the unit update payload for ESF-551.

    Args:
        desired_unit: The desired weight unit (0=kg, 1=lb, 2=st)

    Returns:
        bytearray: The payload to send to the scale to update the display unit
    """
    payload = UNIT_UPDATE_COMMAND.copy()
    payload[5] = 43 - desired_unit
    payload[10] = desired_unit
    return payload
