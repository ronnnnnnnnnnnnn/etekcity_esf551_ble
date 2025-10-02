"""ESF-551 scale implementation."""

import logging
import struct

from ..parser import EtekcitySmartFitnessScale, WeightUnit
from .const import (
    ALIRO_CHARACTERISTIC_UUID,
    DISPLAY_UNIT_KEY,
    HW_REVISION_STRING_CHARACTERISTIC_UUID,
    IMPEDANCE_KEY,
    SW_REVISION_STRING_CHARACTERISTIC_UUID,
    UNIT_UPDATE_COMMAND,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)

_LOGGER = logging.getLogger(__name__)


# === Parsing functions ===

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
    payload = bytearray.fromhex(UNIT_UPDATE_COMMAND)
    payload[5] = 43 - desired_unit
    payload[10] = desired_unit
    return payload


# === Scale class ===

class ESF551Scale(EtekcitySmartFitnessScale):
    """ESF-551 scale implementation with full feature support."""

    # === REQUIRED: Core functionality ===
    
    def _weight_characteristic_uuid(self) -> str:
        """Return the weight notification characteristic UUID for ESF-551."""
        return WEIGHT_CHARACTERISTIC_UUID_NOTIFY

    def _parse_payload(self, payload: bytearray) -> dict[str, int | float | None] | None:
        """Parse raw payload data for ESF-551."""
        return parse(payload)

    # === OPTIONAL: Feature implementations ===
    
    async def _setup_after_connection(self) -> None:
        """
        Perform ESF-551 specific setup after connection.
        
        This includes:
        - Reading hardware/software versions from GATT characteristics
        - Handling display unit changes via Aliro characteristic
        """
        try:
            # Read hardware version (only once)
            if not self._hw_version:
                hw_data = await self._client.read_gatt_char(
                    HW_REVISION_STRING_CHARACTERISTIC_UUID
                )
                self._hw_version = hw_data.decode()
                _LOGGER.debug("ESF-551 HW version: %s", self._hw_version)
            
            # Read software version (every connection)
            sw_data = await self._client.read_gatt_char(
                SW_REVISION_STRING_CHARACTERISTIC_UUID
            )
            self._sw_version = sw_data.decode()
            _LOGGER.debug("ESF-551 SW version: %s", self._sw_version)
        except Exception as ex:
            _LOGGER.warning("Could not read ESF-551 version info: %s", ex)

        # Handle display unit change if requested
        if self._unit_update_flag and self._display_unit is not None:
            try:
                payload = build_unit_update_payload(self._display_unit)
                await self._client.write_gatt_char(
                    ALIRO_CHARACTERISTIC_UUID, payload, False
                )
                _LOGGER.debug(
                    "ESF-551 unit change request sent: %s (payload: %s)",
                    self._display_unit,
                    payload.hex()
                )
                self._unit_update_flag = False
            except Exception as ex:
                _LOGGER.error("ESF-551 failed to request unit change: %s", ex)

