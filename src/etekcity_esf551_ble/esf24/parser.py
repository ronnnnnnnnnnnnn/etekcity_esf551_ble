"""ESF-24 scale implementation (experimental)."""

import logging

from ..parser import EtekcitySmartFitnessScale, WeightUnit, ScaleData
from .const import WEIGHT_CHARACTERISTIC_UUID_NOTIFY, DISPLAY_UNIT_KEY, WEIGHT_KEY

_LOGGER = logging.getLogger(__name__)


# === Parsing functions ===

def parse(payload: bytearray) -> dict[str, int | float | None]:
    """
    Parse raw data received from the ESF-24 scale.

    Args:
        payload (bytearray): Raw data received from the scale.

    Returns:
        dict: Dictionary containing parsed data with the following keys:
            - "weight": Weight value in kilograms

    Returns None if the payload format is invalid or unrecognized.

    Note: This is experimental and may need adjustment once the actual
    ESF-24 BLE protocol is analyzed.
    """

    if (
        payload is not None
        and len(payload) == 11
        and payload[5] == 1
        and payload[0:3] == b"\x10\x0b\x15"
    ):
        data = dict[str, int | float | None]()
        weight = int(payload[3:5].hex(), 16)
        data[WEIGHT_KEY] = round(float(weight) / 100, 2)
        return data
    return None


# === Scale class ===

class ESF24Scale(EtekcitySmartFitnessScale):
    """
    ESF-24 scale implementation (experimental, weight-only support).
    
    Note: This is an experimental implementation. The ESF-24 protocol is not fully
    analyzed yet. Currently only supports basic weight readings.
    
    Limitations:
    - Display unit is fixed to kilograms (protocol unknown)
    - No hardware/software version reading
    - No impedance measurements
    
    These will be implemented when the ESF-24 BLE protocol is analyzed.
    """

    def __init__(self, *args, **kwargs):
        """
        Initialize ESF-24 scale.
        
        Note: display_unit parameter is ignored for ESF-24.
        The scale always reports in kilograms.
        """
        # Remove display_unit if provided, log a warning
        if 'display_unit' in kwargs:
            _LOGGER.warning(
                "ESF-24 does not support display unit changes. "
                "Ignoring display_unit parameter (fixed to kg)."
            )
            kwargs.pop('display_unit')
        
        super().__init__(*args, **kwargs)
        
        # Force display unit to kg
        self._display_unit = WeightUnit.KG
        self._unit_update_flag = False

    @property
    def display_unit(self):
        """ESF-24 display unit is always kg."""
        return WeightUnit.KG

    @display_unit.setter
    def display_unit(self, value):
        """ESF-24 does not support display unit changes."""
        if value is not None and value != WeightUnit.KG:
            _LOGGER.warning(
                "ESF-24 does not support display unit changes. "
                "Display unit will remain as kg."
            )

    # === REQUIRED: Core functionality ===
    
    def _weight_characteristic_uuid(self) -> str:
        """Return the weight notification characteristic UUID for ESF-24."""
        return WEIGHT_CHARACTERISTIC_UUID_NOTIFY

    def _parse_payload(self, payload: bytearray) -> dict[str, int | float | None] | None:
        """
        Parse raw payload data for ESF-24.
        
        Note: This is experimental and needs to be updated once the actual
        ESF-24 BLE protocol is analyzed.
        """
        _LOGGER.debug("Parsing ESF-24 payload (experimental): %s", payload.hex())
        return parse(payload)

    # === OPTIONAL: Feature implementations ===
    
    def _build_scale_data(self, parsed_data: dict[str, int | float | None], name: str, address: str) -> ScaleData:
        """
        Build ScaleData for ESF-24, forcing display unit to kg.
        
        Since we don't know the ESF-24 protocol yet, we force the display
        unit to kg regardless of what's in the payload.
        """
        # Force display unit to kg
        parsed_data[DISPLAY_UNIT_KEY] = WeightUnit.KG
        
        # Use base class implementation
        return super()._build_scale_data(parsed_data, name, address)

