from ._version import __version__, __version_info__
from .esf551 import ESF551Scale, EtekcitySmartFitnessScaleWithBodyMetrics
from .esf551.body_metrics import BodyMetrics, Sex
from .const import (
    ALIRO_CHARACTERISTIC_UUID,
    DISPLAY_UNIT_KEY,
    IMPEDANCE_KEY,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)
from .esf551.const import (
    HW_REVISION_STRING_CHARACTERISTIC_UUID,
    SW_REVISION_STRING_CHARACTERISTIC_UUID,
    UNIT_UPDATE_COMMAND,
)
from .esf24 import ESF24Scale
from .parser import (
    BluetoothScanningMode,
    ConnectionStatus,
    ScaleData,
    WeightUnit,
)

# Backward compatibility alias
EtekcitySmartFitnessScale = ESF551Scale

__all__ = [
    "EtekcitySmartFitnessScale",
    "ESF551Scale",
    "ESF24Scale",
    "EtekcitySmartFitnessScaleWithBodyMetrics",
    "WeightUnit",
    "ScaleData",
    "IMPEDANCE_KEY",
    "WEIGHT_KEY",
    "BodyMetrics",
    "Sex",
    "ConnectionStatus",
    "BluetoothScanningMode",
    # Backward compatibility - ESF-551 constants
    "ALIRO_CHARACTERISTIC_UUID",
    "DISPLAY_UNIT_KEY",
    "HW_REVISION_STRING_CHARACTERISTIC_UUID",
    "SW_REVISION_STRING_CHARACTERISTIC_UUID",
    "UNIT_UPDATE_COMMAND",
    "WEIGHT_CHARACTERISTIC_UUID_NOTIFY",
]
