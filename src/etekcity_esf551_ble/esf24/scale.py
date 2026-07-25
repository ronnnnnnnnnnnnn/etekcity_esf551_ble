"""ESF-24 scale implementation (experimental)."""

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
)
from ..scale import GattScale
from ..data import (
    BluetoothScanningMode,
    ScaleData,
    WeightUnit,
)
from .protocol import (
    CMD_END_MEASUREMENT,
    build_measurement_initiation_command,
    build_unit_update_command,
    is_measurement_frame,
    parse_weight,
)

_STATE_UNIT_SET = 1
_STATE_MEASUREMENT_INIT = 2
_STATE_SETTLING_LOGGED = 4


class ESF24Scale(GattScale):
    """
    ESF-24 scale implementation (experimental, weight and impedance support).

    The final measurement frame carries dual-band BIA impedance, reported
    raw in ohms: 50 kHz under IMPEDANCE_KEY (usable with BodyMetrics) and
    500 kHz under IMPEDANCE_500KHZ_KEY.

    Limitations:
    - No hardware/software version reading
    """

    def __init__(
        self,
        address: str,
        notification_callback,
        display_unit: WeightUnit = WeightUnit.KG,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend=None,
        cooldown_seconds: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        enforced_unit = (
            WeightUnit(display_unit) if display_unit is not None else WeightUnit.KG
        )
        super().__init__(
            address,
            notification_callback,
            enforced_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
            cooldown_seconds,
            logger,
        )
        self._state_mask = 0

    @GattScale.display_unit.setter
    def display_unit(self, value):
        if value is None:
            raise ValueError("ESF-24 requires a non-null display unit")
        self._display_unit = WeightUnit(value)

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """Handle post-connection setup and start notifications."""
        self._state_mask = 0
        try:
            self._logger.debug(
                "ESF-24 starting session for device %s (%s)",
                ble_device.name,
                ble_device.address,
            )
            if weight_char := self._client.services.get_characteristic(
                WEIGHT_CHARACTERISTIC_UUID_NOTIFY
            ):
                await self._client.start_notify(
                    weight_char,
                    lambda char, data: self._notification_handler(
                        char, data, ble_device.name, ble_device.address
                    ),
                )
            else:
                self._logger.error("Weight notification characteristic not found")
                # With Bluetooth proxies, services may not be immediately available.
                # Don't force disconnect - let it fail naturally or timeout.
                return
        except Exception as ex:
            self._logger.exception("%s(%s)", type(ex), ex.args)
            self._client = None

    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        # Dump every frame so a weigh-in can be reconstructed from a debug log;
        # the branches below only announce the ones they act on.
        self._logger.debug("ESF-24 RX payload: %s", payload.hex())
        if data := parse_weight(payload):
            self._logger.debug(
                "ESF-24 stable weight received (%s). Scheduling measurement end command.",
                address,
            )
            self._spawn_task(
                self._safe_write(CMD_END_MEASUREMENT), name="esf24-end-measurement"
            )

            scale_data = ScaleData()
            scale_data.name = name
            scale_data.address = address
            scale_data.display_unit = self.display_unit
            scale_data.measurements = data

            self._notification_callback(scale_data)
        elif is_measurement_frame(payload):
            # Measurement frames stream continuously while the weight settles,
            # dozens per weigh-in, and only the final one carries a reading.
            # Log the first to show the stream arrived, then stay quiet.
            if not self._state_mask & _STATE_SETTLING_LOGGED:
                self._state_mask |= _STATE_SETTLING_LOGGED
                self._logger.debug(
                    "ESF-24 weight settling on %s; waiting for the final frame.",
                    address,
                )
        elif len(payload) == 15 and payload[0:3] == b"\x12\x0f\x15":
            if not self._state_mask & _STATE_UNIT_SET:
                self._state_mask |= _STATE_UNIT_SET
                self._logger.debug(
                    "ESF-24 unit negotiation frame received from %s. Scheduling update.",
                    address,
                )
                cmd = build_unit_update_command(self.display_unit)
                self._spawn_task(self._safe_write(cmd), name="esf24-unit-update")
        elif len(payload) == 11 and payload[0:3] == b"\x14\x0b\x15":
            if not self._state_mask & _STATE_MEASUREMENT_INIT:
                self._state_mask |= _STATE_MEASUREMENT_INIT
                self._logger.debug(
                    "ESF-24 measurement initiation requested by %s. Sending timestamp.",
                    address,
                )
                cmd = build_measurement_initiation_command()
                self._spawn_task(self._safe_write(cmd), name="esf24-measurement-init")
        else:
            self._logger.debug(
                "ESF-24 ignoring unrecognized payload: %s", payload.hex()
            )

    async def _safe_write(self, data: bytearray) -> None:
        """Write GATT char safely with error handling."""
        if not self._client:
            self._logger.warning("ESF-24 cannot send command; no active client")
            return
        if not (
            command_char := self._client.services.get_characteristic(
                ALIRO_CHARACTERISTIC_UUID
            )
        ):
            self._logger.warning(
                "ESF-24 command characteristic not found, skipping write"
            )
            return
        try:
            await self._client.write_gatt_char(command_char, data)
            self._logger.debug("ESF-24 command sent: %s", data.hex())
        except Exception as ex:
            self._logger.error("ESF-24 failed to send command %s: %s", data.hex(), ex)
            self._state_mask = 0
