from __future__ import annotations

import asyncio
import dataclasses
import logging
import platform
import struct
from collections.abc import Callable
from enum import IntEnum, StrEnum
from typing import Any

from bleak import BleakClient
from bleak.assigned_numbers import AdvertisementDataType
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import (
    AdvertisementData,
    BaseBleakScanner,
    get_platform_scanner_backend_type,
)
from bleak_retry_connector import establish_connection

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

SYSTEM = platform.system()
IS_LINUX = SYSTEM == "Linux"
IS_MACOS = SYSTEM == "Darwin"


if IS_LINUX:
    from bleak.backends.bluezdbus.advertisement_monitor import OrPattern
    from bleak.backends.bluezdbus.scanner import BlueZScannerArgs

    # or_patterns is a workaround for the fact that passive scanning
    # needs at least one matcher to be set. The below matcher
    # will match all devices.
    PASSIVE_SCANNER_ARGS = BlueZScannerArgs(
        or_patterns=[
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x02"),
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x06"),
            OrPattern(0, AdvertisementDataType.FLAGS, b"\x1a"),
        ]
    )

if IS_MACOS:
    from bleak.backends.corebluetooth.scanner import CBScannerArgs


class BluetoothScanningMode(StrEnum):
    PASSIVE = "passive"
    ACTIVE = "active"


SCANNING_MODE_TO_BLEAK: dict[BluetoothScanningMode, str] = {
    BluetoothScanningMode.ACTIVE: "active",
    BluetoothScanningMode.PASSIVE: "passive",
}


class ConnectionStatus(IntEnum):
    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2


class WeightUnit(IntEnum):
    """Weight units."""

    KG = 0  # Kilograms
    LB = 1  # Pounds
    ST = 2  # Stones


@dataclasses.dataclass
class ScaleData:
    """
    Response data with information about the scale and measurements.

    Attributes:
        name (str): Name of the scale device.
        address (str): Bluetooth address of the scale.
        hw_version (str): Hardware version of the scale.
        sw_version (str): Software version of the scale.
        display_unit (WeightUnit): Current display unit of the scale.
        measurements (dict): Dictionary containing measurement data:
            - "weight": Weight value in kilograms
            - "impedance": Bioelectrical impedance value (if available)
            - Additional body metrics when used with EtekcitySmartFitnessScaleWithBodyMetrics
    """

    name: str = ""
    address: str = ""
    hw_version: str = ""
    sw_version: str = ""
    display_unit: WeightUnit = WeightUnit.KG
    measurements: dict[str, str | float | None] = dataclasses.field(
        default_factory=dict
    )


def parse(payload: bytearray) -> dict[str, int | float | None]:
    """
    Parse raw data received from the scale.

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


class EtekcitySmartFitnessScale:
    """
    Interface for Etekcity Smart Fitness Scale.

    This class handles BLE connection, data parsing, and unit conversion
    for Etekcity smart scales. It manages the Bluetooth connection lifecycle
    and processes notifications from the scale.

    Attributes:
        address: The BLE MAC address of the scale
        hw_version: Hardware version string of the connected scale
        sw_version: Software version string of the connected scale
        display_unit: The current display unit of the scale (KG, LB, or ST)
    """

    _client: BleakClient = None
    _hw_version: str = None
    _sw_version: str = None
    _display_unit: WeightUnit = None
    _unit_update_flag: bool = False

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
    ) -> None:
        """
        Initialize the scale interface.

        Args:
            address: Bluetooth address of the scale
            notification_callback: Function to call when weight data is received
            display_unit: Preferred weight unit (KG, LB, or ST). If specified,
                          the scale will be instructed to change its display unit
                          to this value upon connection.
            scanning_mode: Mode for BLE scanning (ACTIVE or PASSIVE)
            adapter: Bluetooth adapter to use (Linux only)
            bleak_scanner_backend: Optional custom BLE scanner backend
        """
        _LOGGER.info(f"Initializing EtekcitySmartFitnessScale for address: {address}")

        self.address = address
        self._notification_callback = notification_callback

        if bleak_scanner_backend is None:
            scanner_kwargs: dict[str, Any] = {
                "detection_callback": self._advertisement_callback,
                "service_uuids": None,
                "scanning_mode": SCANNING_MODE_TO_BLEAK[scanning_mode],
                "bluez": {},
                "cb": {},
            }

            if IS_LINUX:
                # Only Linux supports multiple adapters
                if adapter:
                    scanner_kwargs["adapter"] = adapter
                if scanning_mode == BluetoothScanningMode.PASSIVE:
                    scanner_kwargs["bluez"] = PASSIVE_SCANNER_ARGS
            elif IS_MACOS:
                # We want mac address on macOS
                scanner_kwargs["cb"] = {"use_bdaddr": True}

            PlatformBleakScanner = get_platform_scanner_backend_type()
            self._scanner = PlatformBleakScanner(**scanner_kwargs)
        else:
            self._scanner = bleak_scanner_backend
            self._scanner.register_detection_callback(self._advertisement_callback)
        self._lock = asyncio.Lock()
        self._unit_update_buff = bytearray.fromhex(UNIT_UPDATE_COMMAND)
        if display_unit != None:
            self.display_unit = display_unit

    @property
    def hw_version(self) -> str:
        return self._hw_version

    @property
    def sw_version(self) -> str:
        return self._sw_version

    @property
    def display_unit(self):
        return self._display_unit

    @display_unit.setter
    def display_unit(self, value):
        if value != None:
            self._display_unit = value
            self._unit_update_flag = True

    async def async_start(self) -> None:
        """Start the callbacks."""
        _LOGGER.debug(
            "Starting EtekcitySmartFitnessScale for address: %s", self.address
        )
        try:
            async with self._lock:
                await self._scanner.start()
        except Exception as ex:
            _LOGGER.error("Failed to start scanner: %s", ex)
            raise

    async def async_stop(self) -> None:
        """Stop the callbacks."""
        _LOGGER.debug(
            "Stopping EtekcitySmartFitnessScale for address: %s", self.address
        )
        try:
            async with self._lock:
                await self._scanner.stop()
        except Exception as ex:
            _LOGGER.error("Failed to stop scanner: %s", ex)
            raise

    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        """
        Handle notifications received from the scale.

        This method processes the raw data received from the scale's notification
        characteristic and calls the notification callback with the parsed data.

        Args:
            _: The GATT characteristic that sent the notification (unused)
            payload: Raw binary data received from the scale
            name: Device name of the scale
            address: Bluetooth address of the scale
        """
        if data := parse(payload):
            _LOGGER.debug(
                "Received stable weight notification from %s (%s): %s",
                name,
                address,
                data,
            )
            device = ScaleData()
            device.name = name
            device.address = address
            device.hw_version = self.hw_version
            device.sw_version = self.sw_version
            _LOGGER.debug("%s (%s): %s", name, address, data)
            device.display_unit = WeightUnit(data.pop(DISPLAY_UNIT_KEY))

            if self._display_unit == None:
                self._display_unit = device.display_unit
                self._unit_update_flag = False
            else:
                self._unit_update_flag = device.display_unit != self._display_unit

            device.measurements = data
            self._notification_callback(device)

    def _unavailable_callback(self, _: BleakClient) -> None:
        """
        Handle disconnection events from the scale.

        This method is called when the scale disconnects, either intentionally
        or due to connection loss.

        Args:
            _: The BleakClient instance that disconnected (unused)
        """
        self._client = None
        _LOGGER.debug("Scale disconnected")

    async def _advertisement_callback(
        self, ble_device: BLEDevice, _: AdvertisementData
    ) -> None:
        """
        Handle Bluetooth advertisements from the scale.

        This method is called when an advertisement from the target scale
        is detected. It establishes a connection to the scale and sets up
        the necessary characteristics and notifications.

        Args:
            ble_device: The detected Bluetooth device
            _: Advertisement data (unused)
        """
        if ble_device.address != self.address:
            return
        
        async with self._lock:
            if self._client != None:
                return
            try:
                _LOGGER.debug("Connecting to scale: %s", self.address)
                self._client = await establish_connection(
                    BleakClient,
                    ble_device,
                    self.address,
                    self._unavailable_callback,
                )
                _LOGGER.debug("Connected to scale: %s", self.address)
            except Exception as ex:
                _LOGGER.exception("Could not connect to scale: %s(%s)", type(ex), ex.args)
                self._client = None
                return

        try:
            if self._unit_update_flag:
                if self._display_unit != None:
                    self._unit_update_buff[5] = 43 - self._display_unit
                    self._unit_update_buff[10] = self._display_unit
                    await self._client.write_gatt_char(
                        ALIRO_CHARACTERISTIC_UUID, self._unit_update_buff, False
                    )
                    _LOGGER.debug(
                        "Trying to update display unit to %s (buffer: %s)",
                        self._display_unit,
                        self._unit_update_buff.hex(),
                    )
            await self._client.start_notify(
                WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )
            if not self._hw_version:
                self._hw_version = (
                    await self._client.read_gatt_char(
                        HW_REVISION_STRING_CHARACTERISTIC_UUID
                    )
                ).decode()
            self._sw_version = (
                await self._client.read_gatt_char(
                    SW_REVISION_STRING_CHARACTERISTIC_UUID
                )
            ).decode()
            _LOGGER.debug("Scale HW version: %s", self._hw_version)
            _LOGGER.debug("Scale SW version: %s", self._sw_version)
        except Exception as ex:
            _LOGGER.exception("%s(%s)", type(ex), ex.args)
            self._client = None
            self._unit_update_flag = True
