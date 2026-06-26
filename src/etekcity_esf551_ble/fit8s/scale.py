"""FIT8S scale implementation (advertisement-based)."""

from ..const import DISPLAY_UNIT_KEY
from ..scale import AdvertisementScale
from ..data import WeightUnit
from .protocol import parse


class FIT8SScale(AdvertisementScale):
    """
    FIT8S scale — reads weight and impedance from BLE advertisement manufacturer data.

    No GATT connection is established; measurements are received passively from
    the scale's periodic advertisements.
    """

    _model_name = "FIT8S"

    def _parse(self, payload: bytearray) -> dict[str, float | int] | None:
        return parse(payload, self.address)

    def _display_unit_for(self, parsed: dict[str, float | int]) -> WeightUnit | None:
        return WeightUnit(parsed.pop(DISPLAY_UNIT_KEY))
