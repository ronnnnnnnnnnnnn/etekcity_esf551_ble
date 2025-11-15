"""ESF-551 scale implementation."""

import logging
import struct

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..parser import EtekcitySmartFitnessScale, ScaleData, WeightUnit
from ..const import ALIRO_CHARACTERISTIC_UUID, IMPEDANCE_KEY, WEIGHT_CHARACTERISTIC_UUID_NOTIFY, DISPLAY_UNIT_KEY, WEIGHT_KEY
from .const import (
    HW_REVISION_STRING_CHARACTERISTIC_UUID,
    SW_REVISION_STRING_CHARACTERISTIC_UUID,
    UNIT_UPDATE_COMMAND,
)

_LOGGER = logging.getLogger(__name__)


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


class ESF551Scale(EtekcitySmartFitnessScale):
    """ESF-551 scale implementation with full feature support."""
    _unit_update_flag: bool = False


    @EtekcitySmartFitnessScale.display_unit.setter
    def display_unit(self, value):
        if value is not None:
            self._display_unit = value
            self._unit_update_flag = True

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """Handle post-connection setup and start notifications."""
        try:
            _LOGGER.debug(
                "ESF-551 preparing session for device %s (%s)",
                ble_device.name,
                ble_device.address,
            )
            # Perform model-specific setup (read versions, handle unit changes, etc.)
            await self._setup_after_connection()

            # Start receiving weight notifications
            await self._client.start_notify(
                WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )
        except Exception as ex:  # pragma: no cover – log and reset on any failure
            _LOGGER.exception("%s(%s)", type(ex), ex.args)
            self._client = None
            # Trigger a unit update attempt on next connection
            self._unit_update_flag = True

            
    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        if parsed_data := parse(payload):
            _LOGGER.debug(
                "Received stable weight notification from %s (%s): %s",
                name,
                address,
                parsed_data,
            )
            
            scale_data = ScaleData()
            scale_data.name = name
            scale_data.address = address
            scale_data.hw_version = self.hw_version
            scale_data.sw_version = self.sw_version
            
            # Extract and handle display unit
            scale_data.display_unit = WeightUnit(parsed_data.pop(DISPLAY_UNIT_KEY))
            
            if self._display_unit is None:
                self._display_unit = scale_data.display_unit
                self._unit_update_flag = False
            else:
                self._unit_update_flag = scale_data.display_unit != self._display_unit
            
            # Remaining data goes to measurements
            scale_data.measurements = parsed_data
            
            # Call user's callback
            self._notification_callback(scale_data)
    
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

