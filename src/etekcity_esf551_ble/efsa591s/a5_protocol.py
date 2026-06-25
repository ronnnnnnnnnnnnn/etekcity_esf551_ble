"""
A5 encrypted transport for the EFS-A591S-KUS (Apex HR) scale.

The scale uses an "A5" RPC framing over GATT FFF1 (notify) / FFF2 (write);
measurement data is AES-128-CBC encrypted with a key established by a
small-number Diffie-Hellman handshake.

Handshake / crypto summary
--------------------------
1. Client sends KEY_EXCHANGE (0x4201) carrying a small-number DH: modulus ``d``
   (prime, 40000-46340), base ``e`` (prime, 10-100), and ``f = e**g mod d``
   where ``g`` is the client's secret exponent (5-20).
2. Scale replies with its public value ``h``.
3. shared = h**g mod d  ->  key = SHA256(f"{shared}".encode() + b"," + reversed_mac)[:16]
4. Client generates a random 16-byte IV and sends it in KEY_VERIFY (0x4202),
   encrypted with (key, zero-IV).
5. Measurement frames (0x4421) are AES-CBC(key, iv); weight = uint24_le(pt[0:3]) / 1000 kg.

This module is transport-agnostic and side-effect free so it can be unit tested
against captured frames.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import struct
import time
from typing import NamedTuple

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ---- protocol constants ---------------------------------------------------

A5_MAGIC = 0xA5
FLAG_APP_WRITE = 0x23

OPCODE_KEY_EXCHANGE = 0x4201   # OP_HIGH_SECURITY_KEY_EXCHANGE
OPCODE_KEY_VERIFY = 0x4202     # OP_HIGH_SECURITY_KEY_VERIFY
OPCODE_MEASUREMENT = 0x4421    # live weight push (resource 21 44 00)
OPCODE_RESULT = 0x443a         # final result: weight + impedance (resource 3a 44 00)
OPCODE_SET_UNIT = 0xa163       # config: set the scale's display unit (0=kg, 1=lb, 2=st)

CHANNEL_PLAINTEXT = 0x00
CHANNEL_AES = 0x01             # the AES-encrypted measurement channel

# DH parameter ranges
DH_MOD_MIN, DH_MOD_MAX = 40000, 46340   # prime modulus d
DH_BASE_MIN, DH_BASE_MAX = 10, 100      # prime base e
DH_EXP_MIN, DH_EXP_MAX = 5, 20          # secret exponent g


# ---- framing --------------------------------------------------------------

def _checksum(frame_without_cksum: bytes) -> int:
    """byte[5] is set so the sum of all frame bytes ≡ 0xFF (mod 256)."""
    return (0xFF - (sum(frame_without_cksum) & 0xFF)) & 0xFF


def build_frame(seq: int, opcode: int, payload: bytes, channel: int) -> bytes:
    """
    Assemble an A5 frame:
        [0]=0xA5 [1]=flags [2]=seq [3:5]=len(LE) [5]=checksum
        [6]=0x01 [7:9]=opcode(LE) [9]=0x00 [10]=channel [11:]=payload
    where len = total - 6.
    """
    body = bytes([0x01]) + struct.pack("<H", opcode) + bytes([0x00, channel]) + payload
    header = bytes([A5_MAGIC, FLAG_APP_WRITE, seq & 0xFF]) + struct.pack("<H", len(body))
    frame = bytearray(header + bytes([0x00]) + body)  # 0x00 = checksum placeholder
    frame[5] = _checksum(frame)
    return bytes(frame)


class ParsedFrame(NamedTuple):
    flags: int
    seq: int
    opcode: int
    channel: int
    payload: bytes


def parse_frame(data: bytes) -> ParsedFrame | None:
    """Parse a complete A5 frame (after reassembly). Returns None if malformed."""
    if len(data) < 11 or data[0] != A5_MAGIC:
        return None
    length = struct.unpack("<H", data[3:5])[0]
    if len(data) != length + 6:
        return None
    opcode = struct.unpack("<H", data[7:9])[0]
    return ParsedFrame(
        flags=data[1], seq=data[2], opcode=opcode, channel=data[10], payload=data[11:]
    )


class FrameReassembler:
    """Reassemble A5 frames from BLE notification fragments (total = len + 6)."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._expected = 0

    def feed(self, chunk: bytes):
        """Feed one notification payload; yield each complete frame."""
        for b in chunk:
            if not self._buf:
                if b != A5_MAGIC:
                    continue
                self._buf.append(b)
            else:
                self._buf.append(b)
                if len(self._buf) == 5:
                    self._expected = struct.unpack("<H", bytes(self._buf[3:5]))[0] + 6
                if self._expected and len(self._buf) == self._expected:
                    frame = bytes(self._buf)
                    self._buf = bytearray()
                    self._expected = 0
                    yield frame


# ---- AES ------------------------------------------------------------------

def _aes_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(ciphertext) + dec.finalize()


def _aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(plaintext) + enc.finalize()


def _pkcs7_pad(data: bytes, block: int = 16) -> bytes:
    pad = block - (len(data) % block)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data


# ---- MAC / Diffie-Hellman / key derivation --------------------------------

def reversed_mac_bytes(mac: str) -> bytes:
    """'CF:EA:01:28:86:45' -> b'\\x45\\x86\\x28\\x01\\xea\\xcf' (reversed octets)."""
    octets = bytes(int(x, 16) for x in mac.split(":"))
    return octets[::-1]


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def _rand_prime(lo: int, hi: int) -> int:
    while True:
        n = secrets.randbelow(hi - lo + 1) + lo
        if _is_prime(n):
            return n


class DHParams(NamedTuple):
    d: int  # prime modulus
    e: int  # prime base
    g: int  # secret exponent
    f: int  # public value = e**g mod d


def generate_dh() -> DHParams:
    d = _rand_prime(DH_MOD_MIN, DH_MOD_MAX)
    e = _rand_prime(DH_BASE_MIN, DH_BASE_MAX)
    g = secrets.randbelow(DH_EXP_MAX - DH_EXP_MIN + 1) + DH_EXP_MIN
    return DHParams(d=d, e=e, g=g, f=pow(e, g, d))


def compute_shared(scale_public_h: int, g: int, d: int) -> int:
    return pow(scale_public_h, g, d)


def derive_key(shared: int, mac: str) -> bytes:
    digest = hashlib.sha256(str(shared).encode() + b"," + reversed_mac_bytes(mac)).digest()
    return digest[:16]


# ---- handshake messages ---------------------------------------------------

def _tz_byte() -> int:
    """Local UTC offset encoded as the app does: rawOffset_seconds * 2 / 3600."""
    off = -time.timezone if time.localtime().tm_isdst == 0 else -time.altzone
    return (off * 2 // 3600) & 0xFF


def build_key_exchange(seq: int, mac: str, dh: DHParams) -> bytes:
    """OP_HIGH_SECURITY_KEY_EXCHANGE (0x4201), plaintext channel."""
    rmac = reversed_mac_bytes(mac)
    ts = int(time.time())
    payload = (
        struct.pack("<I", ts)
        + bytes([_tz_byte(), len(rmac)])
        + rmac
        + struct.pack("<H", dh.d)
        + bytes([dh.e])
        + struct.pack("<H", dh.f)
    )
    return build_frame(seq, OPCODE_KEY_EXCHANGE, payload, CHANNEL_PLAINTEXT)


def parse_key_exchange_response(frame: bytes) -> int | None:
    """Extract the scale's public value h from a 0x4201 response frame."""
    parsed = parse_frame(frame)
    if parsed is None or parsed.opcode != OPCODE_KEY_EXCHANGE:
        return None
    r = parsed.payload
    if len(r) < 2:
        return None
    p = r[1]  # mac length
    if len(r) < p + 4:
        return None
    return struct.unpack("<H", r[p + 2:p + 4])[0]


def build_key_verify(seq: int, mac: str, iv: bytes, key: bytes) -> bytes:
    """
    OP_HIGH_SECURITY_KEY_VERIFY (0x4202): deliver our random IV to the scale.

    Inner payload = [0x0c][reversed_mac(6)][0x10][iv(16)], AES-CBC encrypted with
    (key, zero-IV), sent on the AES channel.
    """
    rmac = reversed_mac_bytes(mac)
    inner = bytes([0x0C]) + rmac + bytes([len(iv)]) + iv
    ciphertext = _aes_cbc_encrypt(key, bytes(16), _pkcs7_pad(inner))
    return build_frame(seq, OPCODE_KEY_VERIFY, ciphertext, CHANNEL_AES)


def build_set_unit(seq: int, unit: int, key: bytes, iv: bytes) -> bytes:
    """
    Build a display-unit change command (resource 0xa163).

    The plaintext payload is a single byte = the desired unit (0=kg, 1=lb, 2=st),
    AES-CBC/PKCS7 encrypted with the session (key, iv) and sent on the AES channel
    to FFF2 — captured from the app, which writes exactly this on connect and on
    any unit toggle.
    """
    if unit not in (0, 1, 2):
        raise ValueError(f"unit must be 0 (kg), 1 (lb) or 2 (st); got {unit}")
    ciphertext = _aes_cbc_encrypt(key, iv, _pkcs7_pad(bytes([unit])))
    return build_frame(seq, OPCODE_SET_UNIT, ciphertext, CHANNEL_AES)


def random_iv() -> bytes:
    return os.urandom(16)


# ---- measurement decoding -------------------------------------------------

class Measurement(NamedTuple):
    weight_kg: float
    impedance: int | None  # whole-body impedance in ohms (final result only)
    timestamp: int
    final: bool            # True for the 0x443a result frame
    raw: bytes
    heart_rate: int | None = None  # bpm, present on the final result once measured
    display_unit: int | None = None  # unit shown on the scale: 0=kg, 1=lb, 2=st


def decrypt_frame_payload(key: bytes, iv: bytes, parsed: ParsedFrame) -> bytes:
    ct = parsed.payload
    ct = ct[: len(ct) // 16 * 16]
    return _pkcs7_unpad(_aes_cbc_decrypt(key, iv, ct))


def parse_measurement(plaintext: bytes) -> Measurement | None:
    """
    Decode a decrypted live-weight frame (0x4421).

    Layout (16 bytes): [0:3]=weight grams (uint24 LE) /1000 kg, [7:11]=timestamp.
    """
    if len(plaintext) < 11:
        return None
    weight = int.from_bytes(plaintext[0:3], "little") / 1000.0
    timestamp = struct.unpack("<I", plaintext[7:11])[0]
    return Measurement(
        weight_kg=round(weight, 2), impedance=None,
        timestamp=timestamp, final=False, raw=plaintext,
    )


def parse_result(plaintext: bytes) -> Measurement | None:
    """
    Decode a decrypted final-result frame (0x443a).

    Layout (38 bytes): [0:8]=serial ascii, [8:20]=name, [20:22]=00,
    [22:25]=weight grams (uint24 LE) /1000 kg, [25:27]=impedance (uint16 LE) ohms,
    [29:33]=timestamp, [35]=display unit (0=kg, 1=lb, 2=st),
    [36]=heart rate (bpm, 0 until measured).
    """
    if len(plaintext) < 33:
        return None
    weight = int.from_bytes(plaintext[22:25], "little") / 1000.0
    impedance = struct.unpack("<H", plaintext[25:27])[0]
    timestamp = struct.unpack("<I", plaintext[29:33])[0]
    # Display unit the scale showed this reading in. Same encoding as the ESF-551
    # (0=kg, 1=lb, 2=st). Confirmed at byte[35] by a kg-vs-lb capture diff (it
    # flips 1->0 between lb and kg while bytes 33/34 stay constant). Only 0/1/2
    # are accepted; anything else is treated as "unknown".
    display_unit = plaintext[35] if len(plaintext) >= 36 else None
    if display_unit not in (0, 1, 2):
        display_unit = None
    # Heart rate is one byte near the end of the frame; 0 means "not measured"
    # (e.g. user stepped off before it locked, or not barefoot on the electrodes).
    heart_rate = plaintext[36] if len(plaintext) >= 37 and plaintext[36] else None
    return Measurement(
        weight_kg=round(weight, 2),
        impedance=impedance if 0 < impedance < 60000 else None,
        timestamp=timestamp, final=True, raw=plaintext,
        heart_rate=heart_rate,
        display_unit=display_unit,
    )
