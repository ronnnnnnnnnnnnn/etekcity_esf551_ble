"""ESF-24 scale implementation (experimental)."""

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..const import (
    ALIRO_CHARACTERISTIC_UUID,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
)
from ..scale import GattScale, ScaleSessionError
from ..data import (
    BluetoothScanningMode,
    ScaleData,
    WeightUnit,
)
from .protocol import (
    CMD_END_MEASUREMENT,
    build_measurement_initiation_command,
    build_stored_measurement_query,
    build_unit_update_command,
    is_measurement_frame,
    is_stored_measurement_frame,
    parse_stored_measurement,
    parse_weight,
)

_STATE_UNIT_SET = 1
_STATE_MEASUREMENT_INIT = 2
_STATE_SETTLING_LOGGED = 4
# Set once the stored-measurement query has been sent this session.
_STATE_STORED_QUERY = 8

# Ack of our set-time (0x20) command, capture-verified: 21 05 15 01 3c.
_SET_TIME_ACK_FRAME_PREFIX = b"\x21\x05\x15"
_SET_TIME_ACK_FRAME_LENGTH = 5

# Stored offline-measurement record. Matched on the opcode alone so a
# record whose shape the parser rejects still reaches the handler's warning.
_STORED_MEASUREMENT_OPCODE = b"\x23"


class ESF24Scale(GattScale):
    """
    ESF-24 scale implementation (experimental, weight and impedance support).

    The final measurement frame carries dual-band BIA impedance, reported
    raw in ohms: 50 kHz under IMPEDANCE_KEY (usable with BodyMetrics) and
    500 kHz under IMPEDANCE_500KHZ_KEY.

    ``clear_stored_measurements`` (default ``False``) drains the scale's
    store of offline measurements — readings taken while nothing was
    connected — once per session, via a query sent after the scale acks
    our set-time command. Delivering a stored record deletes it from the
    scale (there is no separate delete command), so enabling this hides
    those readings from any other client: leave it off if the official
    VeSync app should still import them. Drained records are logged at
    debug level and discarded for now.

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
        cooldown_seconds: int = GattScale.DEFAULT_COOLDOWN_SECONDS,
        logger: logging.Logger | None = None,
        *,
        clear_stored_measurements: bool = False,
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
        self._clear_stored_measurements = clear_stored_measurements

    @GattScale.display_unit.setter
    def display_unit(self, value):
        if value is None:
            raise ValueError("ESF-24 requires a non-null display unit")
        self._display_unit = WeightUnit(value)

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        """Handle post-connection setup and start notifications."""
        self._state_mask = 0
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
            # Service discovery can transiently come back without the notify
            # characteristic; raising lets the base disconnect and retry on the next
            # advertisement instead of parking a dead client.
            raise ScaleSessionError(
                "ESF-24 weight notification characteristic not found"
            )

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
        elif (
            len(payload) == _SET_TIME_ACK_FRAME_LENGTH
            and payload[0:3] == _SET_TIME_ACK_FRAME_PREFIX
        ):
            # Ack of our set-time command. Recognized even with the drain
            # disabled so it is never logged as unrecognized; it doubles as
            # the trigger for the stored-measurement query because that is
            # where the vendor app sends it (before end-measurement).
            self._logger.debug("ESF-24 set-time acknowledged by %s.", address)
            self._query_stored_measurements(address)
        elif payload[0:1] == _STORED_MEASUREMENT_OPCODE:
            # Dispatched on the opcode alone, not the full frame shape: a
            # 0x23 the parser rejects is a protocol anomaly the handler
            # should warn about, not an unknown payload to pass over.
            self._handle_stored_measurement(payload, address)
        else:
            self._logger.debug(
                "ESF-24 ignoring unrecognized payload: %s", payload.hex()
            )

    def _query_stored_measurements(self, address: str) -> None:
        """Send the stored-measurement query once per session (if enabled).

        Delivery of the returned records deletes them from the scale's
        store, which is exactly the "clear" the option promises.
        """
        if (
            not self._clear_stored_measurements
            or self._state_mask & _STATE_STORED_QUERY
        ):
            return
        self._state_mask |= _STATE_STORED_QUERY
        self._logger.debug(
            "ESF-24 querying stored offline measurements on %s to clear them.",
            address,
        )
        self._spawn_task(
            self._safe_write(build_stored_measurement_query()),
            name="esf24-stored-query",
        )

    def _handle_stored_measurement(self, payload: bytearray, address: str) -> None:
        """Handle a stored offline-measurement record.

        Sent by the scale only in response to our stored-measurement
        query, one frame per offline reading (``count=0`` when the store
        is empty). Delivery deletes the record from the scale, so simply
        receiving and discarding it here is what clears the store. Never
        fires the measurement callback.
        """
        if not is_stored_measurement_frame(payload):
            self._logger.warning(
                "ESF-24 stored-measurement frame from %s has unexpected "
                "length; ignoring: %s",
                address,
                payload.hex(),
            )
            return
        frame = parse_stored_measurement(payload)
        if frame is None:
            self._logger.warning(
                "ESF-24 stored-measurement frame from %s failed its checksum; "
                "ignoring: %s",
                address,
                payload.hex(),
            )
            return
        if frame.count == 0:
            self._logger.debug(
                "ESF-24 stored-measurement store on %s is empty.", address
            )
            return
        self._logger.debug(
            "ESF-24 discarding stored offline measurement %d/%d from %s: "
            "weight=%.2f kg, r1=%d, r2=%d, timestamp=%d (delivery clears it "
            "from the scale).",
            frame.index,
            frame.count,
            address,
            frame.weight_kg,
            frame.resistance_1,
            frame.resistance_2,
            frame.timestamp,
        )

    async def _safe_write(self, data: bytearray) -> None:
        """Write GATT char safely with error handling."""
        if not self._client:
            # Benign: writes are scheduled from the notification handler while
            # the connection is live, so this only fires when a disconnect wins
            # the race to the next event-loop tick. Nothing to act on.
            self._logger.debug("ESF-24 cannot send command; no active client")
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
