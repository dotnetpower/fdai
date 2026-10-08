"""Pure-Python Ed25519 signature verification (RFC 8032, standard library only).

The remediation-pack helper runs on developer machines that may not have a cryptography
library. This module verifies the pack's DSSE signature with only ``hashlib``. It follows the
RFC 8032 reference algorithm and is used only for verification of one small message, so its
speed is adequate. It ships in every pack as ``tools/fdai_ed25519.py``.

Signing never happens here; FDAI signs with an audited library adapter.
"""

from __future__ import annotations

import base64
import binascii
import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")

Point = tuple[int, int, int, int]


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _add(left: Point, right: Point) -> Point:
    a = (left[1] - left[0]) * (right[1] - right[0]) % _P
    b = (left[1] + left[0]) * (right[1] + right[0]) % _P
    c = 2 * left[3] * right[3] * _D % _P
    d = 2 * left[2] * right[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiply(scalar: int, point: Point) -> Point:
    result: Point = (0, 1, 1, 0)
    while scalar > 0:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(left: Point, right: Point) -> bool:
    return (left[0] * right[2] - right[0] * left[2]) % _P == 0 and (
        left[1] * right[2] - right[1] * left[2]
    ) % _P == 0


def _decompress(encoded: bytes) -> Point | None:
    if len(encoded) != 32:
        return None
    y = int.from_bytes(encoded, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0)
if _GX is None:  # pragma: no cover - constant base point always decodes
    raise RuntimeError("invalid Ed25519 base point")
_G: Point = (_GX, _GY, 1, _GX * _GY % _P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return ``True`` when ``signature`` is a valid Ed25519 signature of ``message``."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    point_a = _decompress(public_key)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    digest = hashlib.sha512(signature[:32] + public_key + message).digest()
    h = int.from_bytes(digest, "little") % _L
    return _equal(_multiply(s, _G), _add(point_r, _multiply(h, point_a)))


def parse_public_key(text: str) -> bytes:
    """Parse a PEM SubjectPublicKeyInfo or 64-hex raw Ed25519 public key into 32 bytes."""
    stripped = text.strip()
    if len(stripped) == 64:
        try:
            return bytes.fromhex(stripped)
        except ValueError:
            pass
    lines = [line for line in stripped.splitlines() if line and not line.startswith("-----")]
    try:
        der = base64.b64decode("".join(lines), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public key is neither PEM nor 64-hex Ed25519") from exc
    if len(der) != 44 or not der.startswith(_SPKI_PREFIX):
        raise ValueError("public key is not an Ed25519 SubjectPublicKeyInfo")
    return der[12:]


def key_id(public_key: bytes) -> str:
    """Return the stable key id FDAI uses for a raw Ed25519 public key."""
    return "ed25519:" + hashlib.sha256(public_key).hexdigest()[:16]


__all__ = ["key_id", "parse_public_key", "verify"]
