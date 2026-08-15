from ._version import __version__, __version_info__
from .body_metrics import BaseBodyMetrics, BodyMetrics, BodyMetricsV2, Sex, calc_age
from .const import (
    DISPLAY_UNIT_KEY,
    HEART_RATE_KEY,
    IMPEDANCE_500KHZ_KEY,
    IMPEDANCE_KEY,
    WEIGHT_KEY,
)
from .data import (
    BluetoothScanningMode,
    ScaleData,
    WeightUnit,
)
from .detection import (
    CAPABILITIES,
    ETEKCITY_MANUFACTURER_ID,
    QN_MANUFACTURER_ID,
    ScaleCapabilities,
    ScaleModel,
    detect_model,
    is_etekcity_frame,
    parse_model_code,
)
from .efsa591s import EFSA591SScale
from .efsc651 import EFSC651Scale
from .esf24 import ESF24Scale
from .esf37 import ESF37Scale
from .esf551 import ESF551Scale
from .fit8s import FIT8SScale
from .scale import (
    AdvertisementScale,
    EtekcitySmartFitnessScale,
    GattScale,
)

# Model -> concrete client class. detection.py stays import-light (no client
# imports), so this map lives here where the classes are already imported.
SCALE_CLASSES: dict[ScaleModel, type[EtekcitySmartFitnessScale]] = {
    ScaleModel.ESF551: ESF551Scale,
    ScaleModel.ESF24: ESF24Scale,
    ScaleModel.FIT8S: FIT8SScale,
    ScaleModel.EFSA591S: EFSA591SScale,
    ScaleModel.EFSC651: EFSC651Scale,
    ScaleModel.ESF37: ESF37Scale,
}

__all__ = [
    "__version__",
    "__version_info__",
    "EtekcitySmartFitnessScale",
    "GattScale",
    "AdvertisementScale",
    "ESF551Scale",
    "ESF24Scale",
    "FIT8SScale",
    "EFSA591SScale",
    "EFSC651Scale",
    "ESF37Scale",
    "WeightUnit",
    "ScaleData",
    "HEART_RATE_KEY",
    "IMPEDANCE_500KHZ_KEY",
    "IMPEDANCE_KEY",
    "WEIGHT_KEY",
    "BaseBodyMetrics",
    "BodyMetrics",
    "BodyMetricsV2",
    "Sex",
    "calc_age",
    "BluetoothScanningMode",
    "DISPLAY_UNIT_KEY",
    "CAPABILITIES",
    "ETEKCITY_MANUFACTURER_ID",
    "QN_MANUFACTURER_ID",
    "SCALE_CLASSES",
    "ScaleCapabilities",
    "ScaleModel",
    "detect_model",
    "is_etekcity_frame",
    "parse_model_code",
]
