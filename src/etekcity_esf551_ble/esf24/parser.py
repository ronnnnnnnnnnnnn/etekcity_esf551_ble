"""ESF-24 scale implementation (experimental)."""

from ast import Pass
import asyncio
import logging
import struct
import time
from typing import Callable

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import BaseBleakScanner

from ..const import ALIRO_CHARACTERISTIC_UUID, WEIGHT_CHARACTERISTIC_UUID_NOTIFY, DISPLAY_UNIT_KEY, WEIGHT_KEY

from ..parser import BluetoothScanningMode, EtekcitySmartFitnessScale, WeightUnit, ScaleData
from .const import CMD_END_MEASUREMENT, CMD_SET_DISPLAY_UNIT


_LOGGER = logging.getLogger(__name__)

def build_unit_update_command(desired_unit: WeightUnit) -> bytearray:
    """
    Build the unit update command for ESF24.

    Args:
        desired_unit: The desired weight unit (0=kg, 1=lb, 2=st)

    Returns:
        bytearray: The payload to send to the scale to update the display unit
    """
    payload = CMD_SET_DISPLAY_UNIT.copy()
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
    ts = int(time.time()) - 946656000
    struct.pack_into('<I', cmd, 3, ts)
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

    Returns None if the payload format is invalid or unrecognized.

    Note: This is experimental and may need adjustment once the actual
    ESF-24 BLE protocol is analyzed.
    """
    data = dict[str, int | float | None]()
    weight = int(payload[3:5].hex(), 16)
    data[WEIGHT_KEY] = round(float(weight) / 100, 2)
    return data

class ESF24Scale(EtekcitySmartFitnessScale):
    """
    ESF-24 scale implementation (experimental, weight-only support).
    
    Note: This is an experimental implementation. The ESF-24 protocol is not fully
    analyzed yet. Currently only supports basic weight readings.
    
    Limitations:
    - No hardware/software version reading
    - No impedance measurements
    
    These will be implemented when the ESF-24 BLE protocol is analyzed.
    """

    _state_mask: int = 0

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """Handle post-connection setup and start notifications."""
        try:
            # Start receiving weight notifications
            await self._client.start_notify(
                WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )
        except Exception as ex:
            _LOGGER.exception("%s(%s)", type(ex), ex.args)
            self._client = None


    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        if (
            len(payload) == 11
            and payload[5] == 1
            and payload[0:3] == b"\x10\x0b\x15"
        ):
            if not self._state_mask & 4:
                self._state_mask |= 4
                # LOG SENDING END MEASUREMENT COMMAND FOR DEBUGGING
                asyncio.create_task(self._safe_write(CMD_END_MEASUREMENT))
                data = parse_weight(payload)

                _LOGGER.debug(
                    "Received stable weight notification from %s (%s): %s",
                    name,
                    address,
                    data,
                )
                
                scale_data = ScaleData()
                scale_data.name = name
                scale_data.address = address
                scale_data.display_unit = self.display_unit
                scale_data.measurements = data
                
                self._notification_callback(scale_data)
        elif (
            len(payload) == 15
            and payload[0:3] == b"\x12\x0f\x15"
        ):
            if not self._state_mask & 1:
                self._state_mask |= 1
                cmd = build_unit_update_command(self.display_unit)
                # LOG SENDING UNIT UPDATE COMMAND FOR DEBUGGING
                asyncio.create_task(self._safe_write(cmd))
        elif (
            len(payload) == 11
            and payload[0:3] == b"\x14\x0b\x15"
        ):
            if not self._state_mask & 2:
                self._state_mask |= 2
                cmd = build_measurement_initiation_command()
                # LOG SENDING MEASUREMENT INITIATION COMMAND FOR DEBUGGING
                asyncio.create_task(self._safe_write(cmd))

    async def _safe_write(self, data: bytearray) -> None:
        """Write GATT char safely with error handling."""
        try:
            await self._client.write_gatt_char(ALIRO_CHARACTERISTIC_UUID, data)
        except Exception as ex:
            # LOG ERROR
            pass
