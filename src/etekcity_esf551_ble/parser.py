"""Deprecated module. Use `etekcity_esf551_ble.scale` or `etekcity_esf551_ble.data` instead."""

import warnings

from .data import BluetoothScanningMode, ScaleData, WeightUnit
from .scale import AdvertisementScale, EtekcitySmartFitnessScale, GattScale

warnings.warn(
    "The 'etekcity_esf551_ble.parser' module is deprecated. "
    "Please import from 'etekcity_esf551_ble.scale' or 'etekcity_esf551_ble.data' instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AdvertisementScale",
    "BluetoothScanningMode",
    "EtekcitySmartFitnessScale",
    "GattScale",
    "ScaleData",
    "WeightUnit",
]
