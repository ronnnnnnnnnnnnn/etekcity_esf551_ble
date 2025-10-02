"""
Backward compatibility module for const imports.

This module redirects to esf551.const for backward compatibility.
New code should import directly from esf551.const or from the main package.
"""

# Backward compatibility: redirect to esf551 constants
from .esf551.const import (
    ALIRO_CHARACTERISTIC_UUID,
    DISPLAY_UNIT_KEY,
    HW_REVISION_STRING_CHARACTERISTIC_UUID,
    IMPEDANCE_KEY,
    SW_REVISION_STRING_CHARACTERISTIC_UUID,
    UNIT_UPDATE_COMMAND,
    WEIGHT_CHARACTERISTIC_UUID_NOTIFY,
    WEIGHT_KEY,
)

__all__ = [
    "ALIRO_CHARACTERISTIC_UUID",
    "DISPLAY_UNIT_KEY",
    "HW_REVISION_STRING_CHARACTERISTIC_UUID",
    "IMPEDANCE_KEY",
    "SW_REVISION_STRING_CHARACTERISTIC_UUID",
    "UNIT_UPDATE_COMMAND",
    "WEIGHT_CHARACTERISTIC_UUID_NOTIFY",
    "WEIGHT_KEY",
]
