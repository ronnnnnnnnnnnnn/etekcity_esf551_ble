"""ESF-24 scale implementation (experimental)."""

import asyncio
import logging
import struct
import time

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..const import ALIRO_CHARACTERISTIC_UUID, WEIGHT_CHARACTERISTIC_UUID_NOTIFY, WEIGHT_KEY
from ..parser import BluetoothScanningMode, EtekcitySmartFitnessScale, ScaleData, WeightUnit
from .const import CMD_END_MEASUREMENT, CMD_SET_DISPLAY_UNIT


_LOGGER = logging.getLogger(__name__)

_STATE_UNIT_SET = 1
_STATE_MEASUREMENT_INIT = 2
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


class ESF24Scale(EtekcitySmartFitnessScale):
    """
    ESF-24 scale implementation (experimental, weight-only support).

    Limitations:
    - No hardware/software version reading
    - No impedance measurements
    """

    def __init__(
        self,
        address: str,
        notification_callback,
        display_unit: WeightUnit = WeightUnit.KG,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend=None,
    ) -> None:
        enforced_unit = WeightUnit(display_unit) if display_unit is not None else WeightUnit.KG
        super().__init__(
            address,
            notification_callback,
            enforced_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
        )
        self._state_mask = 0

    @EtekcitySmartFitnessScale.display_unit.setter
    def display_unit(self, value):
        if value is None:
            raise ValueError("ESF-24 requires a non-null display unit")
        self._display_unit = WeightUnit(value)

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """Handle post-connection setup and start notifications."""
        self._state_mask = 0
        try:
            _LOGGER.debug(
                "ESF-24 starting session for device %s (%s)",
                ble_device.name,
                ble_device.address,
            )
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
            _LOGGER.debug(
                "ESF-24 stable weight received (%s). Scheduling measurement end command.",
                address,
            )
            asyncio.create_task(self._safe_write(CMD_END_MEASUREMENT), name="esf24-end-measurement")
            data = parse_weight(payload)

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
            if not self._state_mask & _STATE_UNIT_SET:
                self._state_mask |= _STATE_UNIT_SET
                _LOGGER.debug(
                    "ESF-24 unit negotiation frame received from %s. Scheduling update.",
                    address,
                )
                cmd = build_unit_update_command(self.display_unit)
                asyncio.create_task(self._safe_write(cmd), name="esf24-unit-update")
        elif (
            len(payload) == 11
            and payload[0:3] == b"\x14\x0b\x15"
        ):
            if not self._state_mask & _STATE_MEASUREMENT_INIT:
                self._state_mask |= _STATE_MEASUREMENT_INIT
                _LOGGER.debug(
                    "ESF-24 measurement initiation requested by %s. Sending timestamp.",
                    address,
                )
                cmd = build_measurement_initiation_command()
                asyncio.create_task(self._safe_write(cmd), name="esf24-measurement-init")
        else:
            _LOGGER.debug("ESF-24 ignoring unrecognized payload: %s", payload.hex())

    async def _safe_write(self, data: bytearray) -> None:
        """Write GATT char safely with error handling."""
        if not self._client:
            _LOGGER.warning("ESF-24 cannot send command; no active client")
            return
        try:
            await self._client.write_gatt_char(ALIRO_CHARACTERISTIC_UUID, data)
            _LOGGER.debug("ESF-24 command sent: %s", data.hex())
        except Exception as ex:
            _LOGGER.error("ESF-24 failed to send command %s: %s", data.hex(), ex)
            self._state_mask = 0
