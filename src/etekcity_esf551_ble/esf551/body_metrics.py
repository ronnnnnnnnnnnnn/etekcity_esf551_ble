"""Deprecated module. Use `etekcity_esf551_ble.body_metrics` or `etekcity_esf551_ble.esf551.scale` instead."""

import warnings

from ..body_metrics import BodyMetrics, Sex
from .scale import ESF551ScaleWithBodyMetrics

warnings.warn(
    "The 'etekcity_esf551_ble.esf551.body_metrics' module is deprecated. "
    "Please import 'BodyMetrics' and 'Sex' from 'etekcity_esf551_ble.body_metrics', "
    "and 'ESF551ScaleWithBodyMetrics' from 'etekcity_esf551_ble.esf551.scale'.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "BodyMetrics",
    "ESF551ScaleWithBodyMetrics",
    "Sex",
]
