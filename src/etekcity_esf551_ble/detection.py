"""Advertisement-based scale model detection.

Two manufacturer-data frame families are recognized.

Company ID 1744 (Etekcity platform)::

    [0]    bit-packed header: the low nibble is the advertisement format
           generation (0-2 all share this layout), the upper bits are
           flags that may vary between advertisements. Generation 1
           devices advertise exactly 0x01 (ESF-551, EFS-A591S, FIT-8S);
           the EFS-C651 is the only known generation-2 scale (0x32) we've
           encountered.
    [1:7]  device MAC address, little-endian
    [7:9]  model identifier, 16-bit big-endian
    [9:]   model-specific payload (e.g. FIT-8S live weight)

Company ID 65535 (QN platform, used by the ESF-24 and ESF-17/18)::

    [0:2]  model identifier, 16-bit big-endian
    [2]    0x01 in all captures
    [3]    varies across advertisements (undecoded)
    [4]    pending stored-record count (varies with device state)
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
_QN_MODEL_START = 0  # BE16 at bytes 0:2
_QN_MAC_SLICE = slice(5, 11)

# Header-byte generations with the frame layout documented above. The
# EFS-C651 is the only known generation-2 scale; every other supported
# Etekcity scale is generation 1.
_KNOWN_GENERATIONS = (0, 1, 2)
_EFSC651_GENERATION = 2


class ScaleModel(StrEnum):
    """Supported scale models.

    Values are persisted by consumers (e.g. HA config entries) — treat them
    as a stable public contract and never change existing values.
    """

    ESF551 = "ESF-551"
    ESF24 = "ESF-24"
    FIT8S = "FIT-8S"
    EFSA591S = "EFS-A591S"
    EFSC651 = "EFS-C651"
    ESF17 = "ESF-17"
    ESF18 = "ESF-18"


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

    Checks the structure only (a known generation nibble in the header
    byte, and the device MAC echoed little-endian at bytes 1-6 when an
    address is available) — it answers "is this an Etekcity-platform
    device?", NOT "is this a scale?". Other Etekcity products might produce
    the same shape. Use it to surface devices whose model identifier is not
    in the registries yet, so unknown/new models are never filtered out
    entirely.
    """
    if len(payload) < _ETEKCITY_MODEL_START + 2:
        return False
    # Only the low nibble of the header identifies the frame layout; the
    # upper bits are flags that may change between advertisements (the
    # EFS-C651 advertises 0x32: generation 2 plus flag bits).
    if payload[0] & 0x0F not in _KNOWN_GENERATIONS:
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
    return int.from_bytes(payload[_QN_MODEL_START : _QN_MODEL_START + 2], "big")


# Model-identifier registries. Unlisted/unknown variants are covered by FALLBACK_MATCHERS.
# Add new codes here as units are reported.
MODEL_CODES: dict[int, ScaleModel] = {
    1: ScaleModel.ESF551,
    2: ScaleModel.ESF551,
    3: ScaleModel.EFSA591S,
    5: ScaleModel.EFSA591S,
    127: ScaleModel.EFSA591S,
    134: ScaleModel.EFSA591S,
    136: ScaleModel.EFSC651,
    49321: ScaleModel.FIT8S,
}

QN_MODEL_CODES: dict[int, ScaleModel] = {
    294: ScaleModel.ESF24,
    946: ScaleModel.ESF24,
    211: ScaleModel.ESF17,
    671: ScaleModel.ESF18,
}

# (company_id, identifier) pairs already reported via the fallback-path
# warning log, so each one is logged once per process instead of on every
# advertisement.
_reported_identifiers: set[tuple[int, int]] = set()

# Fallback matchers, checked in order when no model identifier matches. Each
# entry is (model, required_manufacturer_id | None, fnmatch pattern).
# Patterns are matched case-insensitively against the advertised local name
# and the device address. Every entry here identifies exactly one model
# (device name or model-specific address prefix); the retail name shared by
# several models is handled separately in detect_model.
#
# New entries here usually need a matching "bluetooth" matcher in the HA
# integration's manifest.json, or the advertisement never reaches discovery.
FALLBACK_MATCHERS: list[tuple[ScaleModel, int | None, str]] = [
    (ScaleModel.ESF24, None, "QN-Scale1"),
    (ScaleModel.ESF24, None, "04:AC:44:*"),
    (ScaleModel.EFSC651, ETEKCITY_MANUFACTURER_ID, "CF:E9:06:*"),
    (ScaleModel.ESF551, ETEKCITY_MANUFACTURER_ID, "D0:4D:00:*"),
    (ScaleModel.FIT8S, ETEKCITY_MANUFACTURER_ID, "A9:89:5D:*"),
    (ScaleModel.EFSA591S, ETEKCITY_MANUFACTURER_ID, "CF:EA:01:*"),
]

# Retail name advertised identically by the ESF-551, EFS-A591S and EFS-C651.
# On its own it cannot identify a model; detect_model combines it with the
# header generation.
_SHARED_NAME_PATTERN = "Etekcity *Fitness *Scale*"


def _report_unregistered(
    etekcity_code: int | None, qn_code: int | None, context: str
) -> None:
    """Log an identifier that is not in a registry yet, once per process.

    Every such report lets us extend MODEL_CODES/QN_MODEL_CODES.
    """
    for company, code in (
        (ETEKCITY_MANUFACTURER_ID, etekcity_code),
        (QN_MANUFACTURER_ID, qn_code),
    ):
        if code is None or (company, code) in _reported_identifiers:
            continue
        _reported_identifiers.add((company, code))
        _LOGGER.warning(
            "%s with unrecognized model identifier %d (company ID %d) — "
            "please report this identifier so it can be added to the "
            "registry.",
            context,
            code,
            company,
        )


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

    Ambiguity is never resolved by guessing: a frame carrying a *registered*
    identifier but failing frame validation returns None outright,
    deliberately skipping the fallback matchers; and the retail name shared
    by the ESF-551, EFS-A591S and EFS-C651 only resolves when the header
    generation identifies the EFS-C651 — a generation-1 frame with no usable
    identifier and no model-specific address prefix returns None, because
    misidentification is worse than non-identification (consumers offer a
    manual model chooser for exactly this case).

    For the QN family, the MAC echo is only validated when ``address``
    is a real MAC (colon-separated); pass the address whenever available.
    """
    manufacturer_data = manufacturer_data or {}

    etekcity_code = None
    payload = manufacturer_data.get(ETEKCITY_MANUFACTURER_ID)
    if payload is not None:
        code = parse_model_code(payload)
        if code is not None and code in MODEL_CODES:
            if not is_etekcity_frame(payload, address):
                return None
            return MODEL_CODES[code]
        if is_etekcity_frame(payload, address):
            # Only surface identifiers read off validated frames — the
            # please-report warning below must not cite a code from a
            # payload whose MAC echo failed.
            etekcity_code = code

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
                _report_unregistered(
                    etekcity_code,
                    qn_code,
                    f"Detected likely {model.value} via fallback matcher"
                    f" {pattern!r}",
                )
                return model

    # Shared retail name: three models advertise it, so the name alone never
    # decides. The header generation separates the EFS-C651 (the only known
    # generation-2 scale) from the generation-1 ESF-551/EFS-A591S pair, which
    # nothing else in the advertisement can tell apart — for those, None is
    # returned so consumers fall back to a manual model choice instead of
    # risking a misidentified (and silently broken) configuration.
    payload = manufacturer_data.get(ETEKCITY_MANUFACTURER_ID)
    if (
        local_name
        and payload
        and fnmatch.fnmatch(local_name.lower(), _SHARED_NAME_PATTERN.lower())
    ):
        if payload[0] & 0x0F == _EFSC651_GENERATION:
            _report_unregistered(
                etekcity_code,
                qn_code,
                f"Detected likely {ScaleModel.EFSC651.value} via the shared"
                " scale name on a generation-2 frame",
            )
            return ScaleModel.EFSC651
        _report_unregistered(
            etekcity_code,
            qn_code,
            "Found an Etekcity scale advertising the shared retail name"
            " (ESF-551 or EFS-A591S, indistinguishable without a registered"
            " identifier)",
        )
        _LOGGER.debug(
            "Ambiguous shared-name advertisement (header 0x%02X) from %s —"
            " not classifying",
            payload[0],
            address,
        )
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
        has_impedance=True, has_heart_rate=False, display_unit_settable=True
    ),
    ScaleModel.FIT8S: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=False
    ),
    ScaleModel.EFSA591S: ScaleCapabilities(
        has_impedance=True, has_heart_rate=True, display_unit_settable=True
    ),
    ScaleModel.EFSC651: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=True
    ),
    ScaleModel.ESF17: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=True
    ),
    ScaleModel.ESF18: ScaleCapabilities(
        has_impedance=True, has_heart_rate=False, display_unit_settable=True
    ),
}
