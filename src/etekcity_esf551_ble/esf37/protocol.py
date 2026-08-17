"""ESF-37 protocol helpers.

Reverse-engineered from a btsnoop capture of the official VeSync app talking
to a real ESF-37 (2026-08-15). The scale does not use the shared ``0xfff1``/
``0xfff2`` GATT layout the ESF-551 and friends use — every characteristic
lives under its own vendor-specific 128-bit service, and every command and
notification shares one small framing format::

    [0:4]   magic: fe ef c0 a3
    [4]     command byte
    [5]     payload length N
    [6:6+N] payload
    [6+N]   checksum: sum(cmd, len, payload) & 0xFF

The final weight frame is command ``0xd0`` with an 8-byte payload::

    [0:2]   weight, big-endian uint16, hundredths of a kilogram
    [2:4]   weight, big-endian uint16, hundredths of a pound (same
            reading, sent twice pre-converted; only the kg field is used)
    [4]     status: 0x00 while settling, 0x01 on the final/stable frame
    [5]     constant 0x02 in every capture seen; meaning unknown
    [6]     0x02 when a barefoot BIA reading completed, 0x00 otherwise
            (object-only tests, or a quick weigh with poor foot contact)
    [7]     body fat percentage as a plain integer, only meaningful when
            [6] == 0x02 — see :func:`parse_weight`

Verified against 10 real weigh-ins spanning 14.5-120.2 kg: both the kg and
lb fields agree with the display to within rounding (e.g. a 142 lb reading
decoded to exactly 14200 in the lb field).

Byte [7] is far too small to be impedance in ohms (foot-to-foot BIA is
normally 300-800 ohms; this byte can't exceed 255) but lines up exactly
with the app's displayed body fat percentage, truncated to a whole number
(a 35.5% reading decoded to exactly 35). Confirmed against a **single**
ground-truth reading so far — good enough to trust the byte's meaning, not
yet enough to be sure of its rounding behaviour (truncate vs. round) or to
rule out an off-by-one at the boundary between two integers. Treat as
experimental until checked against a few more known readings.

The scale itself only ever supplies this one figure. Every other metric
the app displays (BMI, water%, muscle mass, bone mass, BMR, visceral/
subcutaneous fat, protein%, metabolic age) is derived client-side from
weight + body fat% + the person's height/age/sex — see
:mod:`etekcity_esf551_ble.body_metrics`. A numeric fit against one full
real reading (weight, all 10 derived metrics, BMI-derived height) did not
land closely enough on either :class:`~etekcity_esf551_ble.body_metrics.BodyMetrics`
or :class:`~etekcity_esf551_ble.body_metrics.BodyMetricsV2` to say which
formula (if either, unmodified) the ESF-37's companion app actually uses,
so this module does not attempt to compute them. Wiring that up needs the
household's real profile (exact height/age/sex, athlete flag) to fit
against, not just a BMI-derived height guess.

The scale also stores a backlog of past readings on-device and flushes it
as a batch when a phone connects, command ``0xd4``, 13-byte payload, one
frame per stored reading::

    [0]     sequence number within this batch, 1-indexed
    [1:6]   always zero in every capture seen; meaning unknown
    [6]     constant 0x02 in every capture seen; meaning unknown (same
            value as the live frame's per-byte-5 constant, offset by one
            here — not confirmed to mean the same thing)
    [7:9]   weight, big-endian uint16, hundredths of a pound
    [9:13]  unix timestamp (seconds), big-endian uint32

Decoded against two real historical batches (22 records total) spanning
2026-08-10 to 2026-08-17: weight and timestamp both check out against the
VeSync app's own history list for several of those dates. Two records (out
of 22) didn't fit this decode at all — plausible readings from a different
household member profile the scale doesn't distinguish at the protocol
level (see :func:`parse_history_record`), or a record sub-type not
understood yet. Only weight comes back this way — there is no body fat%
field in the history-batch format at all (13 bytes doesn't leave room for
one), confirmed by checking the closest-in-time historical records to a
live BIA reading and finding no expanded frame. Body fat% is only ever
available live, in the moment, over the ``0xd0`` frame above.

**Unconfirmed**: whether skipping the app's per-user profile push
(``0xc1``/``0xc2`` — see :class:`~.scale.ESF37Scale`'s docstring for why
weight-only support skips it) also skips the history-batch flush. Every
capture this was reverse-engineered from included the full profile-push
handshake; nobody has yet confirmed a history flush still happens with
just time-sync + init. If it turns out not to, sending the profile-push
sequence for real (not just replaying a captured payload — its own tail
bytes aren't understood well enough to construct one with confidence yet)
would be needed to make this feature actually fire.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from ..const import BODY_FAT_PERCENTAGE_KEY, WEIGHT_KEY

MAGIC = b"\xfe\xef\xc0\xa3"

CMD_TIME_SYNC = 0xC6
CMD_INIT = 0xC0
CMD_MEASUREMENT = 0xD0
CMD_HISTORY = 0xD4

_STATUS_FINAL = 0x01
_BIA_COMPLETE = 0x02
_MEASUREMENT_PAYLOAD_LENGTH = 8
_MEASUREMENT_FRAME_LENGTH = len(MAGIC) + 2 + _MEASUREMENT_PAYLOAD_LENGTH + 1

_HISTORY_PAYLOAD_LENGTH = 13
_HISTORY_FRAME_LENGTH = len(MAGIC) + 2 + _HISTORY_PAYLOAD_LENGTH + 1
_LB_TO_KG = 0.453_592_37


def _checksum(body: bytes) -> int:
    """Mod-256 sum of the command byte, length byte and payload."""
    return sum(body) & 0xFF


def build_frame(cmd: int, payload: bytes = b"") -> bytearray:
    """Build a complete framed command: magic + cmd + len + payload + checksum."""
    body = bytes([cmd, len(payload)]) + payload
    return bytearray(MAGIC + body + bytes([_checksum(body)]))


def build_time_sync_command() -> bytearray:
    """Build the time-sync command (``0xc6``) with the current unix time.

    Capture-verified shape; the app sends this first on every connection.
    Nothing observed in the capture indicates the scale rejects an
    approximate clock, so no attempt is made to match its exact epoch.
    """
    return build_frame(CMD_TIME_SYNC, int(time.time()).to_bytes(4, "big"))


def build_init_command() -> bytearray:
    """Build the init command (``0xc0``) sent right after time-sync.

    Capture-verified payload (``\\x02``); purpose beyond "start streaming"
    unknown. Sent unconditionally — see the module/scale docstrings for why
    the app's per-user profile push (``0xc1``/``0xc2``) is skipped entirely.
    """
    return build_frame(CMD_INIT, bytes([0x02]))


def is_measurement_frame(payload: bytearray) -> bool:
    """Return True if ``payload`` has the ESF-37 measurement-frame shape.

    Matches every frame of a weigh-in, settling or final — see
    :func:`parse_weight` for which of those carries a usable reading.
    """
    if len(payload) != _MEASUREMENT_FRAME_LENGTH:
        return False
    if bytes(payload[0:4]) != MAGIC or payload[4] != CMD_MEASUREMENT:
        return False
    if payload[5] != _MEASUREMENT_PAYLOAD_LENGTH:
        return False
    body = bytes(payload[4 : 4 + 2 + _MEASUREMENT_PAYLOAD_LENGTH])
    return payload[-1] == _checksum(body)


def parse_weight(payload: bytearray) -> dict[str, float] | None:
    """Parse a measurement frame; return None unless it is the final reading.

    Always returns a ``"weight"`` key (kilograms). Also returns
    ``"body_fat_percentage"`` when byte 12 (the BIA-complete flag) reads
    ``0x02`` — i.e. a barefoot reading with good electrode contact — using
    byte 13 as-is. See the module docstring for how confident that decode
    is and what it does (and does not) tell you about the rest of the
    scale's body-composition figures.
    """
    if not is_measurement_frame(payload):
        return None
    if payload[10] != _STATUS_FINAL:
        return None
    weight_centikg = int.from_bytes(payload[6:8], "big")
    data: dict[str, float] = {WEIGHT_KEY: round(weight_centikg / 100, 2)}
    if payload[12] == _BIA_COMPLETE:
        data[BODY_FAT_PERCENTAGE_KEY] = float(payload[13])
    return data


def is_history_frame(payload: bytearray) -> bool:
    """Return True if ``payload`` has the ESF-37 history-batch frame shape.

    See :func:`parse_history_record` for turning one into a reading.
    """
    if len(payload) != _HISTORY_FRAME_LENGTH:
        return False
    if bytes(payload[0:4]) != MAGIC or payload[4] != CMD_HISTORY:
        return False
    if payload[5] != _HISTORY_PAYLOAD_LENGTH:
        return False
    body = bytes(payload[4 : 4 + 2 + _HISTORY_PAYLOAD_LENGTH])
    return payload[-1] == _checksum(body)


def parse_history_record(payload: bytearray) -> dict[str, float | datetime] | None:
    """Parse one record from the scale's on-connect history-batch flush.

    Returns a dict with ``"weight"`` (kilograms, converted from the
    on-the-wire hundredths-of-a-pound field — see the module docstring for
    why there's no lb-native field to prefer here, unlike
    :func:`parse_weight`) and ``"timestamp"`` (timezone-aware UTC
    :class:`~datetime.datetime`, decoded straight from the record's own
    unix timestamp — not "now"). Never includes body fat% or any other
    body-composition key; the format has no room for one.

    Returns None if ``payload`` isn't a valid history-batch frame.
    """
    if not is_history_frame(payload):
        return None
    weight_centipounds = int.from_bytes(payload[13:15], "big")
    weight_kg = round(weight_centipounds / 100 * _LB_TO_KG, 2)
    unix_seconds = int.from_bytes(payload[15:19], "big")
    timestamp = datetime.fromtimestamp(unix_seconds, tz=UTC)
    return {WEIGHT_KEY: weight_kg, "timestamp": timestamp}
