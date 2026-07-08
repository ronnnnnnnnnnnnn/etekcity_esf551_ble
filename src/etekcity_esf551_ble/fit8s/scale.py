"""FIT8S scale implementation (advertisement-based)."""

import logging
from collections.abc import Callable

from bleak.backends.scanner import BaseBleakScanner

from ..const import DISPLAY_UNIT_KEY
from ..scale import AdvertisementScale
from ..data import BluetoothScanningMode, ScaleData, WeightUnit
from .protocol import parse


class FIT8SScale(AdvertisementScale):
    """
    FIT8S scale — reads weight and impedance from BLE advertisement manufacturer data.

    No GATT connection is established; measurements are received passively from
    the scale's periodic advertisements.
    """

    _model_name = "FIT8S"

    def __init__(
        self,
        address: str,
        notification_callback: Callable[[ScaleData], None],
        display_unit: WeightUnit = None,
        scanning_mode: BluetoothScanningMode = BluetoothScanningMode.ACTIVE,
        adapter: str | None = None,
        bleak_scanner_backend: BaseBleakScanner = None,
        logger: logging.Logger | None = None,
        *,
        # The scale re-broadcasts its final frame for the whole advertising
        # burst; the window must outlast the burst to keep one callback per
        # weigh-in. Err long — a genuine re-weigh needs step-off + re-tare +
        # settle, which takes at least this long anyway.
        cooldown_seconds: int = 10,
    ) -> None:
        super().__init__(
            address,
            notification_callback,
            display_unit,
            scanning_mode,
            adapter,
            bleak_scanner_backend,
            logger,
            cooldown_seconds=cooldown_seconds,
        )

    def _parse(self, payload: bytearray) -> dict[str, float | int] | None:
        return parse(payload, self.address)

    def _display_unit_for(self, parsed: dict[str, float | int]) -> WeightUnit | None:
        return WeightUnit(parsed.pop(DISPLAY_UNIT_KEY))
