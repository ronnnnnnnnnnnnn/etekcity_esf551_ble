"""EFS-A591S-KUS (Apex HR) scale — encrypted A5 GATT client."""

from __future__ import annotations

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    HEART_RATE_KEY,
    IMPEDANCE_KEY,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)

from ..scale import GattScale
from ..data import ScaleData, WeightUnit
from . import protocol as a5

_LOGGER = logging.getLogger(__name__)

# Frames the scale emits that carry no data we use (status/flag/ack frames).
# Ignored silently so they don't spam the debug log.
_STATUS_OPCODES = frozenset({0x4202, 0x4420, 0x413B, 0x413D, 0x4434, 0x4436})


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
            _LOGGER.exception(
                "EFS-A591S session setup failed: %s(%s)", type(ex), ex.args
            )
            self._client = None

    async def _send_frame(self, frame: bytes) -> None:
        if self._client and self._write_char:
            await self._client.write_gatt_char(self._write_char, frame, response=False)

    async def _send_verify_then_unit(
        self, verify: bytes, unit_frame: bytes | None
    ) -> None:
        # VERIFY establishes the session; the unit command reuses the same key/iv,
        # so it must go out after VERIFY (and only if a unit is configured).
        await self._send_frame(verify)
        if unit_frame is not None:
            await self._send_frame(unit_frame)

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
            # Push the configured display unit right after VERIFY, the same way
            # the app does on connect (resource 0xa163, encrypted with the session
            # key/iv). Skipped when no unit is configured.
            unit_frame = None
            if self._display_unit is not None:
                unit_frame = a5.build_set_unit(
                    self._next_seq(), int(self._display_unit), self._key, self._iv
                )
            self._spawn_task(
                self._send_verify_then_unit(verify, unit_frame),
                name="efsa591s-verify",
            )

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
        # Prefer the unit the scale actually displayed this reading in (from the
        # result frame); fall back to the client-configured unit if absent.
        scale_data.display_unit = (
            WeightUnit(meas.display_unit)
            if meas.display_unit is not None
            else self._display_unit
        )
        measurements: dict[str, float | int] = {WEIGHT_KEY: meas.weight_kg}
        if meas.impedance:
            measurements[IMPEDANCE_KEY] = meas.impedance
        if meas.heart_rate:
            measurements[HEART_RATE_KEY] = meas.heart_rate
        scale_data.measurements = measurements
        self._notification_callback(scale_data)
