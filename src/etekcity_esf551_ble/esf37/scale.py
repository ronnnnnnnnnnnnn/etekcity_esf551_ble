"""ESF-37 scale implementation."""

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from ..data import ScaleData
from ..scale import GattScale
from .protocol import build_init_command, build_time_sync_command, parse_weight

#: Vendor-specific service 0000191x; characteristics don't use the shared
#: 0xfff1/0xfff2 UUIDs the ESF-551 and friends do.
_WEIGHT_NOTIFY_CHARACTERISTIC_UUID = "00002c12-0000-1000-8000-00805f9b34fb"
_CONTROL_CHARACTERISTIC_UUID = "00002c11-0000-1000-8000-00805f9b34fb"


class ESF37Scale(GattScale):
    """
    ESF-37 scale implementation (experimental, weight only).

    No onboard user-profile support is used. The official app registers a
    profile per household member (``0xc1``) and selects one (``0xc2``)
    before every weigh-in, presumably so the scale itself can compute
    body composition — but the capture this was reverse-engineered from
    shows the scale streams weight identically with that step skipped
    entirely, needing only the time-sync (``0xc6``) and init (``0xc0``)
    commands. Per-person disambiguation is therefore left entirely to the
    caller (e.g. matching against each household member's recent weight
    history), not the scale.

    Limitations:
    - No hardware/software version reading — the Device Information
      service on this model exposes only a PnP ID.
    - No display-unit control — no equivalent of the ESF-551's Aliro
      characteristic was found.
    - No body composition — the final frame carries a few reserved bytes
      beyond the weight fields, but no impedance/BIA field could be
      confirmed from the capture this was built from.
    """

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        try:
            self._logger.debug(
                "ESF-37 preparing session for device %s (%s)",
                ble_device.name,
                ble_device.address,
            )
            weight_char = self._client.services.get_characteristic(
                _WEIGHT_NOTIFY_CHARACTERISTIC_UUID
            )
            control_char = self._client.services.get_characteristic(
                _CONTROL_CHARACTERISTIC_UUID
            )
            if not weight_char or not control_char:
                self._logger.error("ESF-37 required characteristics not found")
                return

            await self._client.start_notify(
                weight_char,
                lambda char, data: self._notification_handler(
                    char, data, ble_device.name, ble_device.address
                ),
            )
            await self._client.write_gatt_char(
                control_char, build_time_sync_command(), response=False
            )
            await self._client.write_gatt_char(
                control_char, build_init_command(), response=False
            )
        except Exception as ex:  # pragma: no cover - log and reset on any failure
            self._logger.exception("%s(%s)", type(ex), ex.args)
            self._client = None

    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        if parsed := parse_weight(payload):
            self._logger.debug(
                "Received stable weight notification from %s (%s): %s",
                name,
                address,
                parsed,
            )
            scale_data = ScaleData()
            scale_data.name = name
            scale_data.address = address
            scale_data.measurements = parsed
            self._notification_callback(scale_data)
