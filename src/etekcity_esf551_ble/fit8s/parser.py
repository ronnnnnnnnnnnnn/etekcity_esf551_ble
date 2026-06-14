"""FIT8S scale implementation (advertisement-based)."""

import logging

from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from ..const import DISPLAY_UNIT_KEY, IMPEDANCE_KEY, WEIGHT_KEY
from ..parser import EtekcitySmartFitnessScale, ScaleData, WeightUnit

_LOGGER = logging.getLogger(__name__)

_PAYLOAD_LENGTH = 20
_STABILITY_BYTE_INDEX = 15


def parse(payload: bytearray, address: str = "") -> dict[str, float | int] | None:
    """
    Parse a FIT8S manufacturer advertisement payload.

    Packet layout (20 bytes, as reported by bleak's manufacturer_data value):
      [0]     : header byte (0x01)
      [1:7]   : device MAC address, little-endian
      [7:10]  : unknown
      [10:13] : weight in grams, 3-byte little-endian int
      [13:15] : bioelectrical impedance in ohms, 2-byte little-endian int (0 = not measured)
      [15]    : stability flag (0x01 = stable reading)
      [16]    : display unit (0x00=kg, 0x01=lb, 0x02=st)
      [17:20] : unknown/constant

    Args:
        payload: 20-byte manufacturer data value from bleak.
        address: BLE MAC address of the scale (e.g. "A9:89:5D:ED:A0:63").
                 When provided, the embedded MAC in bytes 1–6 is validated.

    Returns:
        dict with "weight" in kg, "display_unit" (int), and optionally
        "impedance" in ohms, or None if the payload is invalid or unstable.
    """
    if len(payload) != _PAYLOAD_LENGTH:
        return None
    if address:
        addr_bytes = bytearray(int(b, 16) for b in address.split(":"))[::-1]
        if bytearray(payload[1:7]) != addr_bytes:
            return None
    if payload[_STABILITY_BYTE_INDEX] != 0x01:
        return None
    weight_grams = int.from_bytes(payload[10:13], "little")
    result: dict[str, float | int] = {
        WEIGHT_KEY: round(weight_grams / 1000, 2),
        DISPLAY_UNIT_KEY: int(payload[16]),
    }
    if impedance := int.from_bytes(payload[13:15], "little"):
        result[IMPEDANCE_KEY] = impedance
    return result


class FIT8SScale(EtekcitySmartFitnessScale):
    """
    FIT8S scale — reads weight and impedance from BLE advertisement manufacturer data.

    No GATT connection is established; measurements are received passively from
    the scale's periodic advertisements.
    """

    async def _advertisement_callback(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        if ble_device.address != self.address:
            return

        for mfr_bytes in advertisement_data.manufacturer_data.values():
            payload = bytearray(mfr_bytes)
            _LOGGER.debug(
                "FIT8S raw manufacturer data from %s: %s",
                ble_device.address,
                payload.hex(),
            )
            if parsed := parse(payload, self.address):
                _LOGGER.debug(
                    "FIT8S stable measurement from %s (%s): %s",
                    ble_device.name,
                    ble_device.address,
                    parsed,
                )
                scale_data = ScaleData()
                scale_data.name = ble_device.name or "FIT8S"
                scale_data.address = ble_device.address
                scale_data.display_unit = WeightUnit(parsed.pop(DISPLAY_UNIT_KEY))
                self._display_unit = scale_data.display_unit
                scale_data.measurements = parsed
                self._notification_callback(scale_data)
                return

    def _notification_handler(
        self, _: BleakGATTCharacteristic, payload: bytearray, name: str, address: str
    ) -> None:
        pass  # FIT8S uses advertisement data; GATT notifications are not used

    async def _start_scale_session(self, ble_device: BLEDevice) -> None:
        pass  # FIT8S uses advertisement data; no GATT session is needed
