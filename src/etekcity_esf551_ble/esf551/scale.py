"""ESF-551 scale implementation."""

import logging
import warnings
from datetime import date
from collections.abc import Callable

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import BaseBleakScanner

from ..scale import GattScale
from ..data import BluetoothScanningMode, ScaleData, WeightUnit
from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    HW_REVISION_STRING_CHARACTERISTIC_UUID,
    SW_REVISION_STRING_CHARACTERISTIC_UUID,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    DISPLAY_UNIT_KEY,
    IMPEDANCE_KEY,
    WEIGHT_KEY,
)
from ..body_metrics import BodyMetrics, Sex, _calc_age, _as_dictionary
from .protocol import parse, build_unit_update_payload

_LOGGER = logging.getLogger(__name__)


class ESF551Scale(GattScale):
    """ESF-551 scale implementation with full feature support."""

    _unit_update_flag: bool = False

    @GattScale.display_unit.setter
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
                _LOGGER.error("Weight notification characteristic not found")
                # With Bluetooth proxies, services may not be immediately available.
                # Don't force disconnect - let it fail naturally or timeout.
                return
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
                if hw_char := self._client.services.get_characteristic(
                    HW_REVISION_STRING_CHARACTERISTIC_UUID
                ):
                    hw_data = await self._client.read_gatt_char(hw_char)
                    self._hw_version = hw_data.decode()
                    _LOGGER.debug("ESF-551 HW version: %s", self._hw_version)
                else:
                    _LOGGER.debug("HW version characteristic not found")

            # Read software version (every connection)
            if sw_char := self._client.services.get_characteristic(
                SW_REVISION_STRING_CHARACTERISTIC_UUID
            ):
                sw_data = await self._client.read_gatt_char(sw_char)
                self._sw_version = sw_data.decode()
                _LOGGER.debug("ESF-551 SW version: %s", self._sw_version)
            else:
                _LOGGER.debug("SW version characteristic not found")
        except Exception as ex:
            _LOGGER.warning("Could not read ESF-551 version info: %s", ex)

        # Handle display unit change if requested
        if self._unit_update_flag and self._display_unit is not None:
            try:
                if unit_char := self._client.services.get_characteristic(
                    ALIRO_CHARACTERISTIC_UUID
                ):
                    payload = build_unit_update_payload(self._display_unit)
                    await self._client.write_gatt_char(unit_char, payload, False)
                    _LOGGER.debug(
                        "ESF-551 unit change request sent: %s (payload: %s)",
                        self._display_unit,
                        payload.hex(),
                    )
                    self._unit_update_flag = False
                else:
                    _LOGGER.warning(
                        "Unit update characteristic not found, skipping unit update"
                    )
            except Exception as ex:
                _LOGGER.error("ESF-551 failed to request unit change: %s", ex)


class ESF551ScaleWithBodyMetrics(ESF551Scale):
    """
    Extended ESF-551 scale implementation with body metrics calculations.

    This class extends the ESF-551 scale implementation to automatically calculate
    body composition metrics based on the user's profile (sex, age, height)
    and the measurements from the scale (weight, impedance).

    All the body metrics are added to the ScaleData.measurements dictionary
    before being passed to the notification callback.
    """

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        sex: Sex,
        birthdate: date,
        height_m: float,
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
        cooldown_seconds: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        warnings.warn(
            "ESF551ScaleWithBodyMetrics is deprecated and will be removed in a future release. "
            "Use the standalone BodyMetrics class from the package root instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        self._sex = sex
        self._birthdate = birthdate
        self._height_m = height_m
        self._original_callback = notification_callback

        super().__init__(
            address,
            lambda data: self._wrapped_notification_callback(
                self._sex, self._birthdate, self._height_m, data
            ),
            display_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
            cooldown_seconds,
            logger,
        )

    def _wrapped_notification_callback(
        self, sex: Sex, birthdate: date, height_m: float, data: ScaleData
    ) -> None:
        # Only calculate body metrics if impedance is present
        body_metrics = BodyMetrics(
            data.measurements[WEIGHT_KEY],
            height_m,
            _calc_age(birthdate),
            sex,
            data.measurements.get(IMPEDANCE_KEY),
        )
        if IMPEDANCE_KEY in data.measurements:
            data.measurements |= _as_dictionary(body_metrics)
        else:
            data.measurements["body_mass_index"] = body_metrics.body_mass_index
        self._original_callback(data)
