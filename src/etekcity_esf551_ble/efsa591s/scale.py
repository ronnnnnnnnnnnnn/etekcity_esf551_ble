"""EFS-A591S-KUS (Apex HR) scale — encrypted A5 GATT client."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import date

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import BaseBleakScanner

from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    HEART_RATE_KEY,
    IMPEDANCE_KEY,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)
from ..parser import BluetoothScanningMode, GattScale, ScaleData, WeightUnit
from ..esf551.body_metrics import (
    BodyMetrics,
    Sex,
    _as_dictionary,
    _calc_age,
)
from . import a5_protocol as a5

_LOGGER = logging.getLogger(__name__)

# Frames the scale emits that carry no data we use (status/flag/ack frames).
# Ignored silently so they don't spam the debug log.
_STATUS_OPCODES = frozenset({0x4202, 0x4420, 0x413b, 0x413d, 0x4434, 0x4436})


class EFSA591SScale(GattScale):
    """
    EFS-A591S-KUS (Apex HR Smart Fitness Scale).

    Speaks the scale's "A5" encrypted protocol over GATT FFF0
    (notify FFF1 / write FFF2).  On connect it performs a small-number
    Diffie-Hellman handshake, derives an AES-128-CBC session key from the
    exchange and the device MAC, sends a randomly generated session IV, then
    decrypts the live weight stream.

    Note: key derivation requires the device's real MAC address, so this model
    does not work on platforms where bleak reports a CoreBluetooth UUID instead
    of a MAC (i.e. macOS without ``use_bdaddr``).
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._write_char = None
        self._reasm = a5.FrameReassembler()
        self._seq = 0x0A
        self._dh: a5.DHParams | None = None
        self._key: bytes | None = None
        self._iv: bytes | None = None

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        try:
            _LOGGER.debug(
                "EFS-A591S session for %s (%s)", ble_device.name, ble_device.address
            )
            if ":" not in self.address:
                _LOGGER.error(
                    "EFS-A591S needs the device MAC for key derivation; got '%s'. "
                    "This platform does not expose a MAC (e.g. macOS).",
                    self.address,
                )
                return

            notify_char = self._client.services.get_characteristic(
                WEIGHT_CHARACTERISTIC_UUID_NOTIFY
            )
            self._write_char = self._client.services.get_characteristic(
                ALIRO_CHARACTERISTIC_UUID
            )
            if not notify_char or not self._write_char:
                _LOGGER.error("EFS-A591S required characteristics not found")
                return

            # Reset per-session crypto state
            self._reasm = a5.FrameReassembler()
            self._key = None
            self._iv = None

            await self._client.start_notify(
                notify_char,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )

            # Kick off the DH key exchange
            self._dh = a5.generate_dh()
            frame = a5.build_key_exchange(self._next_seq(), self.address, self._dh)
            _LOGGER.debug("EFS-A591S sending key exchange: %s", frame.hex())
            await self._send_frame(frame)

        except Exception as ex:
            _LOGGER.exception("EFS-A591S session setup failed: %s(%s)", type(ex), ex.args)
            self._client = None

    async def _send_frame(self, frame: bytes) -> None:
        if self._client and self._write_char:
            await self._client.write_gatt_char(self._write_char, frame, response=False)

    def _notification_handler(
        self,
        _: BleakGATTCharacteristic,
        data: bytearray,
        name: str,
        address: str,
    ) -> None:
        # data is a bytearray; FrameReassembler.feed iterates it, so no copy needed.
        for frame in self._reasm.feed(data):
            try:
                self._handle_frame(frame, name, address)
            except Exception as ex:  # pragma: no cover - defensive
                _LOGGER.debug("EFS-A591S frame handling error: %s", ex)

    def _handle_frame(self, frame: bytes, name: str, address: str) -> None:
        parsed = a5.parse_frame(frame)
        if parsed is None:
            return

        if parsed.opcode == a5.OPCODE_KEY_EXCHANGE:
            h = a5.parse_key_exchange_response(frame)
            if h is None or self._dh is None:
                return
            shared = a5.compute_shared(h, self._dh.g, self._dh.d)
            self._key = a5.derive_key(shared, self.address)
            self._iv = a5.random_iv()
            _LOGGER.debug("EFS-A591S key established (h=%d), sending verify", h)
            verify = a5.build_key_verify(
                self._next_seq(), self.address, self._iv, self._key
            )
            asyncio.ensure_future(self._send_frame(verify))

        elif parsed.opcode == a5.OPCODE_RESULT:
            # Only the final result frame carries the stabilized weight plus
            # impedance. We deliberately apply ONLY this frame and ignore the
            # live OPCODE_MEASUREMENT stream below: those intermediate frames
            # carry an unstable, weight-only reading that would otherwise flood
            # history and overwrite the final body-composition values (a live
            # frame arriving after the result frame resets impedance to
            # "unavailable").
            if not self._key or not self._iv:
                return
            pt = a5.decrypt_frame_payload(self._key, self._iv, parsed)
            meas = a5.parse_result(pt)
            if meas is None or meas.weight_kg <= 0:
                return
            self._emit(meas, name, address)
        elif parsed.opcode == a5.OPCODE_MEASUREMENT:
            # Live, pre-stabilization weight stream - intentionally ignored so
            # only the finalized measurement is delivered to Home Assistant.
            return
        elif parsed.opcode not in _STATUS_OPCODES:
            _LOGGER.debug(
                "EFS-A591S unhandled opcode 0x%04x: %s", parsed.opcode, frame.hex()
            )

    def _emit(self, meas: a5.Measurement, name: str, address: str) -> None:
        scale_data = ScaleData()
        scale_data.name = name
        scale_data.address = address
        scale_data.hw_version = self.hw_version or ""
        scale_data.sw_version = self.sw_version or ""
        scale_data.display_unit = self._display_unit
        measurements: dict[str, float | int] = {WEIGHT_KEY: meas.weight_kg}
        if meas.impedance:
            measurements[IMPEDANCE_KEY] = meas.impedance
        if meas.heart_rate:
            measurements[HEART_RATE_KEY] = meas.heart_rate
        scale_data.measurements = measurements
        self._notification_callback(scale_data)


class EFSA591SScaleWithBodyMetrics(EFSA591SScale):
    """
    EFS-A591S-KUS with on-device body-composition calculation.

    Wraps :class:`EFSA591SScale` and, when an impedance value is present (i.e. on
    the final result frame), augments ``ScaleData.measurements`` with body
    metrics (BMI, body-fat %, muscle mass, etc.) computed locally from the user's
    profile using the same :class:`BodyMetrics` engine as the ESF-551.  Frames
    that carry weight only (the live stream) get BMI added.
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
        self._sex = sex
        self._birthdate = birthdate
        self._height_m = height_m
        self._original_callback = notification_callback
        super().__init__(
            address,
            self._wrapped_callback,
            display_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
            cooldown_seconds,
            logger,
        )

    def _wrapped_callback(self, data: ScaleData) -> None:
        metrics = BodyMetrics(
            data.measurements[WEIGHT_KEY],
            self._height_m,
            _calc_age(self._birthdate),
            self._sex,
            data.measurements.get(IMPEDANCE_KEY),
        )
        if IMPEDANCE_KEY in data.measurements:
            data.measurements |= _as_dictionary(metrics)
        else:
            data.measurements["body_mass_index"] = metrics.body_mass_index
        self._original_callback(data)
