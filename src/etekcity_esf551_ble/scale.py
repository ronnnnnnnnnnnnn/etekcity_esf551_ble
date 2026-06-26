from __future__ import annotations

import abc
import asyncio
import logging
import time
import platform
from collections.abc import Callable
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

from .data import BluetoothScanningMode, ScaleData, WeightUnit


_LOGGER = logging.getLogger(__name__)

SYSTEM = platform.system()
IS_LINUX = SYSTEM == "Linux"
IS_MACOS = SYSTEM == "Darwin"


if IS_LINUX:
    from bleak.args.bluez import BlueZScannerArgs, OrPattern

    PASSIVE_OR_PATTERNS = [
        OrPattern(0, AdvertisementDataType.FLAGS, b"\x02"),
        OrPattern(0, AdvertisementDataType.FLAGS, b"\x06"),
        OrPattern(0, AdvertisementDataType.FLAGS, b"\x1a"),
    ]
    PASSIVE_SCANNER_ARGS = BlueZScannerArgs(or_patterns=PASSIVE_OR_PATTERNS)


class EtekcitySmartFitnessScale(abc.ABC):
    """
    Abstract base class for Etekcity Smart Fitness Scale implementations.

    Handles the parts common to every model regardless of how measurements are
    obtained: BLE scanner setup and lifecycle, address filtering, and the
    notification callback. Transport-specific behaviour lives in the
    :class:`GattScale` and :class:`AdvertisementScale` subclasses.

    Attributes:
        address: The BLE MAC address of the scale
        hw_version: Hardware version string of the connected scale
        sw_version: Software version string of the connected scale
        display_unit: The current display unit of the scale (KG, LB, or ST)
    """

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize the scale interface.

        Args:
            address: Bluetooth address of the scale
            notification_callback: Function to call when weight data is received
            display_unit: Preferred weight unit (KG, LB, or ST). Where the model
                          supports it, the scale is instructed to change its
                          display unit to this value.
            scanning_mode: Mode for BLE scanning (ACTIVE or PASSIVE)
            adapter: Bluetooth adapter to use (Linux only)
            bleak_scanner_backend: Optional custom BLE scanner backend
            logger: Optional logger instance. If not provided, uses the library's
                    internal logger.
        """
        self._logger = logger or _LOGGER
        self._logger.info(
            f"Initializing EtekcitySmartFitnessScale for address: {address}"
        )

        self.address = address
        self._hw_version: str | None = None
        self._sw_version: str | None = None
        self._display_unit: WeightUnit | None = None
        self._notification_callback = notification_callback

        if bleak_scanner_backend is None:
            scanner_kwargs: dict[str, Any] = {
                "detection_callback": self._advertisement_callback,
                "service_uuids": None,
                "scanning_mode": BluetoothScanningMode.ACTIVE,
                "bluez": {},
                "cb": {},
            }

            if IS_LINUX:
                # Only Linux supports multiple adapters
                if adapter:
                    scanner_kwargs["adapter"] = adapter
                if scanning_mode == BluetoothScanningMode.PASSIVE:
                    scanner_kwargs["bluez"] = PASSIVE_SCANNER_ARGS
                    scanner_kwargs["scanning_mode"] = BluetoothScanningMode.PASSIVE
            elif IS_MACOS:
                # We want mac address on macOS
                scanner_kwargs["cb"] = {"use_bdaddr": True}

            PlatformBleakScanner, _ = get_platform_scanner_backend_type()
            self._scanner = PlatformBleakScanner(**scanner_kwargs)
        else:
            self._scanner = bleak_scanner_backend
            self._scanner.register_detection_callback(self._advertisement_callback)
        self._lock = asyncio.Lock()
        if display_unit is not None:
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
        if value is not None:
            self._display_unit = value

    @abc.abstractmethod
    async def _advertisement_callback(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """
        Handle Bluetooth advertisements from the target scale.

        Called by the scanner for every detected device. Implementations decide
        what to do with an advertisement from ``self.address``: connect over GATT
        (:class:`GattScale`) or parse the advertisement payload directly
        (:class:`AdvertisementScale`).

        Args:
            ble_device: The detected Bluetooth device
            advertisement_data: Advertisement data for the detected device
        """

    async def async_start(self) -> None:
        """Start the callbacks."""
        self._logger.debug(
            "Starting EtekcitySmartFitnessScale for address: %s", self.address
        )
        try:
            async with self._lock:
                await self._scanner.start()
        except Exception as ex:
            self._logger.error("Failed to start scanner: %s", ex)
            raise

    async def async_stop(self) -> None:
        """Stop the callbacks."""
        self._logger.debug(
            "Stopping EtekcitySmartFitnessScale for address: %s", self.address
        )
        try:
            async with self._lock:
                await self._scanner.stop()
        except Exception as ex:
            self._logger.error("Failed to stop scanner: %s", ex)
            raise


class GattScale(EtekcitySmartFitnessScale, abc.ABC):
    """
    Base class for scales that deliver measurements over a GATT connection.

    On detecting the target scale's advertisement a connection is established and
    model-specific setup runs in :meth:`_start_scale_session`; measurements then
    arrive via :meth:`_notification_handler`. An optional cooldown period ignores
    advertisements for a while after a disconnection.
    """

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
        cooldown_seconds: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        Initialize the GATT scale interface.

        Args:
            cooldown_seconds: Optional cooldown period in seconds to ignore new
                              advertisements after a disconnection.

        See :meth:`EtekcitySmartFitnessScale.__init__` for the remaining args.
        """
        super().__init__(
            address,
            notification_callback,
            display_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
            logger,
        )
        self._client: BleakClient | None = None
        self._initializing: bool = False
        self._cooldown_seconds = cooldown_seconds
        self._cooldown_end_time: float = 0
        self._background_tasks: set[asyncio.Task] = set()

    def _spawn_task(
        self, coro: Any, *, name: str | None = None
    ) -> asyncio.Task:
        """
        Schedule a fire-and-forget coroutine safely.

        Keeps a strong reference to the task until it finishes (CPython only
        weakly references tasks, so an un-stored task can be garbage-collected
        mid-execution) and logs any exception it raises instead of letting it
        vanish silently.
        """
        task = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task.add_done_callback(self._log_task_exception)
        return task

    def _log_task_exception(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            self._logger.error(
                "Background task %s failed: %s", task.get_name(), exc
            )

    @abc.abstractmethod
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

    @abc.abstractmethod
    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """
        Complete model-specific setup after a connection is established.

        Implementations should perform any characteristic reads and register
        notification callbacks (typically via `self._client.start_notify`).
        """
        raise NotImplementedError

    def _unavailable_callback(self, _: BleakClient) -> None:
        """
        Handle disconnection events from the scale.

        This method is called when the scale disconnects, either intentionally
        or due to connection loss.

        Args:
            _: The BleakClient instance that disconnected (unused)
        """
        self._logger.debug("Scale disconnected")
        disconnect_time = time.time()
        self._cooldown_end_time = disconnect_time + self._cooldown_seconds
        self._client = None

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

        # Ignore advertisements received during cooldown period
        # This prevents queued callbacks from being processed after cooldown expires
        if self._cooldown_seconds > 0 and time.time() < self._cooldown_end_time:
            self._logger.debug(
                "Ignoring advertisement during cooldown period (cooldown ends at %s)",
                self._cooldown_end_time,
            )
            return

        async with self._lock:
            if self._client is not None or self._initializing:
                return

            self._initializing = True

        try:
            try:
                self._logger.debug("Connecting to scale: %s", self.address)
                self._client = await establish_connection(
                    BleakClient,
                    ble_device,
                    self.address,
                    self._unavailable_callback,
                )
                self._logger.debug("Connected to scale: %s", self.address)
            except Exception as ex:
                self._logger.exception(
                    "Could not connect to scale: %s(%s)", type(ex), ex.args
                )
                self._client = None
                return

            if not self._client or not self._client.is_connected:
                self._logger.error("Client not connected, skipping setup")
                return

            await self._start_scale_session(ble_device)
        finally:
            self._initializing = False


class AdvertisementScale(EtekcitySmartFitnessScale, abc.ABC):
    """
    Base class for scales that broadcast measurements in their BLE
    advertisements, with no GATT connection.

    Each advertisement from the target scale is passed to :meth:`_parse`; a
    non-``None`` result is wrapped in a :class:`ScaleData` and delivered to the
    notification callback.
    """

    # Fallback device name used when the advertisement carries none.
    _model_name: str = ""

    @EtekcitySmartFitnessScale.display_unit.setter
    def display_unit(self, value):
        # Advertisement-only scales report the unit observed in their
        # advertisements; it cannot be commanded. Ignore writes (but log so the
        # caller can tell why a requested unit had no effect).
        if value is not None:
            self._logger.debug(
                "Ignoring display_unit=%s; %s reports the unit observed in "
                "advertisements and cannot set it on the scale",
                value,
                type(self).__name__,
            )

    @abc.abstractmethod
    def _parse(self, payload: bytearray) -> dict[str, float | int] | None:
        """
        Parse a single manufacturer-data payload into a measurements dict.

        Returns None if the payload is invalid or the reading is not usable
        (e.g. not yet stable).
        """

    def _display_unit_for(self, parsed: dict[str, float | int]) -> WeightUnit | None:
        """
        Return the unit shown on the scale's display for this reading.

        Receives the dict from :meth:`_parse` and may ``pop`` a display-unit
        entry out of it so it does not leak into ``measurements``. Defaults to
        None ("unknown").
        """
        return None

    async def _advertisement_callback(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        if ble_device.address != self.address:
            return

        for mfr_bytes in advertisement_data.manufacturer_data.values():
            payload = bytearray(mfr_bytes)
            self._logger.debug(
                "Raw manufacturer data from %s: %s",
                ble_device.address,
                payload.hex(),
            )
            if parsed := self._parse(payload):
                self._logger.debug(
                    "Stable measurement from %s (%s): %s",
                    ble_device.name,
                    ble_device.address,
                    parsed,
                )
                display_unit = self._display_unit_for(parsed)
                scale_data = ScaleData()
                scale_data.name = ble_device.name or self._model_name
                scale_data.address = ble_device.address
                scale_data.display_unit = display_unit
                scale_data.measurements = parsed
                if display_unit is not None:
                    self._display_unit = display_unit
                self._notification_callback(scale_data)
                return
