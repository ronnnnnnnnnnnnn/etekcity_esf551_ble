"""EFS-C651 encrypted A5 GATT client."""

from __future__ import annotations

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    IMPEDANCE_KEY,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)
from ..data import ScaleData, WeightUnit
from ..efsa591s import protocol as a5
from ..scale import GattScale
from . import protocol

_STATUS_OPCODES = frozenset({0x4202, 0x4420, 0x413B, 0x413D, 0x4434, 0x4436})
_RESULT_OPCODE = 0x4422


class EFSC651Scale(GattScale):
    """
    EFS-C651 Smart Fitness Scale.

    Speaks the same encrypted "A5" protocol as the EFS-A591S over GATT FFF0
    (notify FFF1 / write FFF2): a small-number Diffie-Hellman handshake, an
    AES-128-CBC session key derived from the exchange and the device MAC, then
    an encrypted measurement stream. Only the final result frame is applied;
    the live weight stream is ignored.

    Impedance is reported in an encoded form unique to this model family and
    is decoded in :mod:`.protocol` — see there for the details.

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
            self._logger.debug(
                "EFS-C651 session for %s (%s)", ble_device.name, ble_device.address
            )
            if ":" not in self.address:
                self._logger.error(
                    "EFS-C651 needs the device MAC for key derivation; got '%s'.",
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
                self._logger.error("EFS-C651 required characteristics not found")
                return

            self._reasm = a5.FrameReassembler()
            self._key = None
            self._iv = None
            await self._client.start_notify(
                notify_char,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )

            self._dh = a5.generate_dh()
            frame = a5.build_key_exchange(self._next_seq(), self.address, self._dh)
            self._logger.debug("EFS-C651 sending key exchange: %s", frame.hex())
            await self._send_frame(frame)
        except Exception as ex:
            self._logger.exception(
                "EFS-C651 session setup failed: %s(%s)", type(ex), ex.args
            )
            self._client = None

    async def _send_frame(self, frame: bytes) -> None:
        if self._client and self._write_char:
            await self._client.write_gatt_char(self._write_char, frame, response=False)

    async def _send_verify_then_unit(
        self, verify: bytes, unit_frame: bytes | None
    ) -> None:
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
        for frame in self._reasm.feed(data):
            try:
                self._handle_frame(frame, name, address)
            except Exception as ex:  # pragma: no cover - defensive
                self._logger.debug("EFS-C651 frame handling error: %s", ex)

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
            verify = a5.build_key_verify(
                self._next_seq(), self.address, self._iv, self._key
            )
            unit_frame = None
            if self._display_unit is not None:
                unit_frame = a5.build_set_unit(
                    self._next_seq(), int(self._display_unit), self._key, self._iv
                )
            self._spawn_task(
                self._send_verify_then_unit(verify, unit_frame),
                name="efsc651-verify",
            )
        elif parsed.opcode == _RESULT_OPCODE:
            if not self._key or not self._iv:
                return
            plaintext = a5.decrypt_frame_payload(self._key, self._iv, parsed)
            measurement = protocol.parse_result(plaintext)
            if measurement is None or measurement.weight_kg <= 0:
                return
            self._emit(measurement, name, address)
        elif parsed.opcode == a5.OPCODE_MEASUREMENT:
            return
        elif parsed.opcode not in _STATUS_OPCODES:
            self._logger.debug(
                "EFS-C651 unhandled opcode 0x%04x: %s",
                parsed.opcode,
                frame.hex(),
            )

    def _emit(self, measurement: a5.Measurement, name: str, address: str) -> None:
        scale_data = ScaleData()
        scale_data.name = name
        scale_data.address = address
        scale_data.hw_version = self.hw_version or ""
        scale_data.sw_version = self.sw_version or ""
        scale_data.display_unit = (
            WeightUnit(measurement.display_unit)
            if measurement.display_unit is not None
            else self._display_unit
        )
        scale_data.measurements = {WEIGHT_KEY: measurement.weight_kg}
        if measurement.impedance:
            scale_data.measurements[IMPEDANCE_KEY] = measurement.impedance
        self._notification_callback(scale_data)
