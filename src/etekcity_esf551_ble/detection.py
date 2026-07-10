"""Advertisement-based scale model detection.

Everything in this module is derived from real BLE advertisement captures
of the supported scales (plus fallback matchers carried over from the HA
integration's previously shipped Bluetooth matchers).

Two manufacturer-data frame families are recognized.

Company ID 1744 (Etekcity platform)::

    [0]    0x01 header
    [1:7]  device MAC address, little-endian
    [7:9]  model identifier, 16-bit big-endian
    [9:]   model-specific payload (e.g. FIT-8S live weight)

Company ID 65535 (QingNiu platform, used by the ESF-24)::

    [0]    frame header
    [1:3]  model identifier, 16-bit big-endian
    [3:5]  unknown
    [5:11] device MAC address, little-endian

The model identifier is constant across a unit's advertisements and shared
by units of the same model, but differs per regional/hardware variant, so
one model may map to several codes. Identifiers MUST be compared as the
full 16-bit value: other products share company ID 1744 with different
identifiers at the same offset (e.g. an Etekcity-platform air purifier
advertising ``c6 23``). Company ID 65535 is a catch-all used by many
vendors, so for that family the embedded MAC is validated against the
device address before the identifier is trusted.
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass
from enum import StrEnum

_LOGGER = logging.getLogger(__name__)

ETEKCITY_MANUFACTURER_ID = 1744
QN_MANUFACTURER_ID = 65535

_ETEKCITY_MODEL_START = 7  # BE16 at bytes 7:9, after the embedded MAC
_QN_MODEL_START = 1  # BE16 at bytes 1:3
_QN_MAC_SLICE = slice(5, 11)


class ScaleModel(StrEnum):
    """Supported scale models.

    Values are persisted by consumers (e.g. HA config entries) — treat them
    as a stable public contract and never change existing values.
    """

    ESF551 = "ESF-551"
    ESF24 = "ESF-24"
    FIT8S = "FIT-8S"
    EFSA591S = "EFS-A591S"


def parse_model_code(payload: bytes) -> int | None:
    """Return the model identifier from an Etekcity-platform (1744) payload.

    ``payload`` is the manufacturer-data *value* for company ID 1744 (the
    two-byte company ID already stripped, as bleak and HA report it).
    Returns None if the payload is too short to contain the identifier.
    """
    if len(payload) < _ETEKCITY_MODEL_START + 2:
        return None
    return int.from_bytes(
        payload[_ETEKCITY_MODEL_START : _ETEKCITY_MODEL_START + 2], "big"
    )


def _reversed_mac(address: str) -> bytes | None:
    """Little-endian bytes of a colon-separated MAC, or None if not a MAC."""
    octets = address.split(":")
    if len(octets) != 6:
        return None  # e.g. macOS CoreBluetooth UUID
    try:
        return bytes(int(o, 16) for o in octets)[::-1]
    except ValueError:
        return None


def is_etekcity_frame(payload: bytes, address: str | None = None) -> bool:
    """Return True if ``payload`` has the Etekcity-platform frame shape.

    Checks the structure only (0x01 header, and the device MAC echoed
    little-endian at bytes 1-6 when an address is available) — it answers
    "is this an Etekcity-platform device?", NOT "is this a scale?". Other
    products on the same platform (purifiers, plugs) produce the same
    shape. Use it to surface devices whose model identifier is not in the
    registries yet, so unknown/new models are never filtered out entirely.
    """
    if len(payload) < _ETEKCITY_MODEL_START + 2 or payload[0] != 0x01:
        return False
    if address:
        expected = _reversed_mac(address)
        if expected is not None and payload[1:7] != expected:
            return False
    return True


def _parse_qn_model_code(payload: bytes, address: str | None) -> int | None:
    """Return the model identifier from a QingNiu-platform (65535) payload.

    When a MAC address is available, the MAC echoed at bytes 5-11 must match
    it — company ID 65535 is used by many unrelated vendors, so the echo is
    what makes the frame trustworthy.
    """
    if len(payload) < _QN_MAC_SLICE.stop:
        return None
    if address:
        expected = _reversed_mac(address)
        if expected is not None and payload[_QN_MAC_SLICE] != expected:
            return None
    return int.from_bytes(payload[_QN_MODEL_START : _QN_MODEL_START + 2], "big")


# Model-identifier registries. One model may map to several codes (regional/
# hardware variants). Only capture-verified or previously shipped codes are
# listed; unlisted variants are covered by FALLBACK_MATCHERS. Add new codes
# here as units are reported.
MODEL_CODES: dict[int, ScaleModel] = {
    # ESF-551 (capture-verified; other variants fall back to the name matcher)
    2: ScaleModel.ESF551,
    # EFS-A591S variants (set shipped since integration 0.5.1, validated as a
    # set on EFS-A591S-KUS hardware)
    3: ScaleModel.EFSA591S,
    5: ScaleModel.EFSA591S,
    127: ScaleModel.EFSA591S,
    134: ScaleModel.EFSA591S,
    # FIT-8S (capture-verified; other variants fall back to the OUI matcher)
    49321: ScaleModel.FIT8S,
}

QN_MODEL_CODES: dict[int, ScaleModel] = {
    # ESF-24 (capture-verified). Distinguishes it from other QingNiu-platform
    # scales that advertise the same "QN-Scale*" name family.
    9729: ScaleModel.ESF24,
}

# Identifiers already reported via the fallback-path INFO log, so each one is
# logged once per process instead of on every advertisement.
_reported_identifiers: set[int] = set()

# Fallback matchers, checked in order when no model identifier matches. Each
# entry is (model, required_manufacturer_id | None, fnmatch pattern).
# Patterns are matched case-insensitively against the advertised local name
# and, if given, the device address (HA surfaces the address as the name for
# nameless advertisements, so address prefixes double as name patterns).
# Carried over verbatim from the integration's previously shipped matchers.
FALLBACK_MATCHERS: list[tuple[ScaleModel, int | None, str]] = [
    (ScaleModel.ESF24, None, "QN-Scale1"),
    (ScaleModel.ESF24, None, "04:AC:44:*"),
    (ScaleModel.ESF551, ETEKCITY_MANUFACTURER_ID, "Etekcity *Fitness *Scale*"),
    (ScaleModel.ESF551, ETEKCITY_MANUFACTURER_ID, "D0:4D:00:*"),
    (ScaleModel.FIT8S, ETEKCITY_MANUFACTURER_ID, "A9:89:5D:*"),
    (ScaleModel.EFSA591S, ETEKCITY_MANUFACTURER_ID, "CF:EA:01:*"),
]


def detect_model(
    local_name: str | None,
    manufacturer_data: dict[int, bytes] | None,
    address: str | None = None,
) -> ScaleModel | None:
    """Classify an advertisement; return None if it is not a known scale.

    The model identifier is authoritative when present (it is the only
    signal that separates the EFS-A591S from the ESF-551, whose names
    collide, and the ESF-24 from foreign QingNiu scales sharing its name
    family). Name/address matchers are a fallback for truncated or missing
    manufacturer data.

    For the QN (65535) family, the MAC echo is only validated when
    ``address`` is a real MAC (colon-separated); pass the address whenever
    available.
    """
    manufacturer_data = manufacturer_data or {}

    etekcity_code = None
    payload = manufacturer_data.get(ETEKCITY_MANUFACTURER_ID)
    if payload is not None and is_etekcity_frame(payload, address):
        etekcity_code = parse_model_code(payload)
        if etekcity_code is not None and etekcity_code in MODEL_CODES:
            return MODEL_CODES[etekcity_code]

    payload = manufacturer_data.get(QN_MANUFACTURER_ID)
    if payload is not None:
        code = _parse_qn_model_code(payload, address)
        if code is not None and code in QN_MODEL_CODES:
            return QN_MODEL_CODES[code]

    for model, required_mfr_id, pattern in FALLBACK_MATCHERS:
        if required_mfr_id is not None and required_mfr_id not in manufacturer_data:
            continue
        for candidate in (local_name, address):
            if candidate and fnmatch.fnmatch(candidate.lower(), pattern.lower()):
                if (
                    etekcity_code is not None
                    and etekcity_code not in _reported_identifiers
                ):
                    # A scale variant whose identifier isn't in the registry
                    # yet — every such report lets us extend MODEL_CODES.
                    _reported_identifiers.add(etekcity_code)
                    _LOGGER.info(
                        "Detected %s via fallback matcher %r with unrecognized"
                        " model identifier %d — please report this identifier"
                        " so it can be added to the registry",
                        model.value,
                        pattern,
                        etekcity_code,
                    )
                return model
    return None


@dataclass(frozen=True)
class ScaleCapabilities:
    """What a scale model measures and supports."""

    has_impedance: bool  # body-metrics capable (weight + impedance)
    has_heart_rate: bool
    display_unit_settable: bool  # False = unit is observed-only


CAPABILITIES: dict[ScaleModel, ScaleCapabilities] = {
    ScaleModel.ESF551: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=True
    ),
    ScaleModel.ESF24: ScaleCapabilities(
        has_impedance=False, has_heart_rate=False, display_unit_settable=True
    ),
    ScaleModel.FIT8S: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=False
    ),
    ScaleModel.EFSA591S: ScaleCapabilities(
        has_impedance=True, has_heart_rate=True, display_unit_settable=True
    ),
}
