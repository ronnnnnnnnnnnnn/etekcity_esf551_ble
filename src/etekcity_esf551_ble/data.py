from __future__ import annotations

import dataclasses
from enum import IntEnum, StrEnum


class BluetoothScanningMode(StrEnum):
    PASSIVE = "passive"
    ACTIVE = "active"


class WeightUnit(IntEnum):
    """Weight units."""

    KG = 0  # Kilograms
    LB = 1  # Pounds
    ST = 2  # Stones


@dataclasses.dataclass
class ScaleData:
    """
    Response data with information about the scale and measurements.

    Attributes:
        name (str): Name of the scale device.
        address (str): Bluetooth address of the scale.
        hw_version (str): Hardware version of the scale.
        sw_version (str): Software version of the scale.
        display_unit (WeightUnit): Current display unit of the scale.
        measurements (dict): Dictionary containing measurement data.
    """

    name: str = ""
    address: str = ""
    hw_version: str = ""
    sw_version: str = ""
    display_unit: WeightUnit = WeightUnit.KG
    measurements: dict[str, str | float | None] = dataclasses.field(
        default_factory=dict
    )
