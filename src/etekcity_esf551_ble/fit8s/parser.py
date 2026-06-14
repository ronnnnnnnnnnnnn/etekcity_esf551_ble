"""FIT8S scale implementation (advertisement-based)."""

from ..const import DISPLAY_UNIT_KEY, IMPEDANCE_KEY, WEIGHT_KEY
from ..parser import AdvertisementScale, WeightUnit

_PAYLOAD_LENGTH = 20
_STABILITY_BYTE_INDEX = 15
_MAC_OCTETS = 6


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
        octets = address.split(":")
        # On some platforms (e.g. macOS without use_bdaddr) the address is a
        # CoreBluetooth UUID, not a MAC; skip validation rather than crash.
        if len(octets) != _MAC_OCTETS:
            return None
        addr_bytes = bytearray(int(b, 16) for b in octets)[::-1]
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


class FIT8SScale(AdvertisementScale):
    """
    FIT8S scale — reads weight and impedance from BLE advertisement manufacturer data.

    No GATT connection is established; measurements are received passively from
    the scale's periodic advertisements.
    """

    _model_name = "FIT8S"

    def _parse(self, payload: bytearray) -> dict[str, float | int] | None:
        return parse(payload, self.address)

    def _display_unit_for(
        self, parsed: dict[str, float | int]
    ) -> WeightUnit | None:
        return WeightUnit(parsed.pop(DISPLAY_UNIT_KEY))
