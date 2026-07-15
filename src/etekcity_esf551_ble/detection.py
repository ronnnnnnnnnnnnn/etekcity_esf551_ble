"""Advertisement-based scale model detection.

Two manufacturer-data frame families are recognized.

Company ID 1744 (Etekcity platform)::

    [0]    0x01 header
    [1:7]  device MAC address, little-endian
    [7:9]  model identifier, 16-bit big-endian
    [9:]   model-specific payload (e.g. FIT-8S live weight)

Company ID 65535 (QN platform, used by the ESF-24)::

    [0:2]  model identifier, 16-bit little-endian (QN convention)
    [2:5]  unknown
    [5:11] device MAC address, little-endian

Company ID 65535 is a catch-all used by many vendors, so for that
family the embedded MAC is validated against the device address
before the identifier is trusted.
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
_QN_MODEL_START = 0  # LE16 at bytes 0:2
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
    two-byte company ID already stripped, as bleak already reports it).
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
        return None
    try:
        return bytes(int(o, 16) for o in octets)[::-1]
    except ValueError:
        return None


def is_etekcity_frame(payload: bytes, address: str | None = None) -> bool:
    """Return True if ``payload`` has the Etekcity-platform frame shape.

    Checks the structure only (0x01 header, and the device MAC echoed
    little-endian at bytes 1-6 when an address is available) — it answers
    "is this an Etekcity-platform device?", NOT "is this a scale?". Other
    Etekcity products might produce the same shape. Use it to surface devices
    whose model identifier is not in the registries yet, so unknown/new models
    are never filtered out entirely.
    """
    if len(payload) < _ETEKCITY_MODEL_START + 2 or payload[0] != 0x01:
        return False
    if address:
        expected = _reversed_mac(address)
        if expected is not None and payload[1:7] != expected:
            return False
    return True


def _parse_qn_model_code(payload: bytes, address: str | None) -> int | None:
    """Return the model identifier from a QN payload.

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
    return int.from_bytes(payload[_QN_MODEL_START : _QN_MODEL_START + 2], "little")


# Model-identifier registries. Unlisted/unknown variants are covered by FALLBACK_MATCHERS.
# Add new codes here as units are reported.
MODEL_CODES: dict[int, ScaleModel] = {
    2: ScaleModel.ESF551,
    3: ScaleModel.EFSA591S,
    5: ScaleModel.EFSA591S,
    127: ScaleModel.EFSA591S,
    134: ScaleModel.EFSA591S,
    49321: ScaleModel.FIT8S,
}

QN_MODEL_CODES: dict[int, ScaleModel] = {
    9729: ScaleModel.ESF24,
}

# (company_id, identifier) pairs already reported via the fallback-path
# warning log, so each one is logged once per process instead of on every
# advertisement.
_reported_identifiers: set[tuple[int, int]] = set()

# Fallback matchers, checked in order when no model identifier matches. Each
# entry is (model, required_manufacturer_id | None, fnmatch pattern).
# Patterns are matched case-insensitively against the advertised local name.
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
    collide, and the ESF-24 from other QN scales sharing its name family).
    Name/address matchers are a fallback for truncated or missing
    manufacturer data.

    For the QN family, the MAC echo is only validated when ``address``
    is a real MAC (colon-separated); pass the address whenever available.
    """
    manufacturer_data = manufacturer_data or {}

    etekcity_code = None
    payload = manufacturer_data.get(ETEKCITY_MANUFACTURER_ID)
    if payload is not None and is_etekcity_frame(payload, address):
        etekcity_code = parse_model_code(payload)
        if etekcity_code is not None and etekcity_code in MODEL_CODES:
            return MODEL_CODES[etekcity_code]

    qn_code = None
    payload = manufacturer_data.get(QN_MANUFACTURER_ID)
    if payload is not None:
        qn_code = _parse_qn_model_code(payload, address)
        if qn_code is not None and qn_code in QN_MODEL_CODES:
            return QN_MODEL_CODES[qn_code]

    for model, required_mfr_id, pattern in FALLBACK_MATCHERS:
        if required_mfr_id is not None and required_mfr_id not in manufacturer_data:
            continue
        for candidate in (local_name, address):
            if candidate and fnmatch.fnmatch(candidate.lower(), pattern.lower()):
                # A scale variant whose identifier isn't in a registry yet —
                # every such report lets us extend MODEL_CODES/QN_MODEL_CODES.
                for company, code in (
                    (ETEKCITY_MANUFACTURER_ID, etekcity_code),
                    (QN_MANUFACTURER_ID, qn_code),
                ):
                    if code is None or (company, code) in _reported_identifiers:
                        continue
                    _reported_identifiers.add((company, code))
                    _LOGGER.warning(
                        "Detected likely %s via fallback matcher %r with "
                        "unrecognized model identifier %d (company ID %d) — "
                        "please report this identifier so it can be added to "
                        "the registry.",
                        model.value,
                        pattern,
                        code,
                        company,
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
