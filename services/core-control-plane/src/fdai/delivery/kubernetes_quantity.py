"""Bounded nonnegative Kubernetes quantities for reusable resource accounting."""

from __future__ import annotations

import re
from decimal import ROUND_CEILING, Context, Decimal, DecimalException, localcontext

from kubernetes.utils.quantity import parse_quantity

MAX_RESOURCE_QUANTITY = 2**63 - 1
_MAX_TEXT_LENGTH = 96
_MAX_EXPONENT = 64
_QUANTITY = re.compile(
    r"\+?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
    r"(?:[numkMGTPE]|[KMGTPE]i|[eE](?P<exponent>[+-]?[0-9]+))?"
)


class KubernetesQuantityError(ValueError):
    """Resource evidence is invalid or outside the supported accounting bounds."""


def parse_resource_quantity(value: object) -> Decimal:
    """Return exact base units using the official Kubernetes Python quantity parser.

    CPU base units are cores; memory/storage base units are bytes. This deliberately accepts
    only nonnegative ASCII quantity strings or JSON integers, not booleans, floats or Decimal
    objects. DecimalSI, BinarySI and decimal exponents are supported. Text is bounded to 96
    characters, exponents to +/-64 and magnitude to signed 64-bit. Unsupported evidence raises
    KubernetesQuantityError; it is never coerced to zero, clamped or silently rounded here.
    This is read-side accounting, not an API admission validator or Go canonical serializer.
    """
    if type(value) is int:
        if not 0 <= value <= MAX_RESOURCE_QUANTITY:
            raise KubernetesQuantityError("Kubernetes resource quantity is outside its bounds")
        return Decimal(value)
    if not isinstance(value, str) or not 0 < len(value) <= _MAX_TEXT_LENGTH:
        raise KubernetesQuantityError(
            "Kubernetes resource quantity must be bounded text or integer"
        )
    matched = _QUANTITY.fullmatch(value)
    if matched is None:
        raise KubernetesQuantityError("Kubernetes resource quantity syntax is invalid")
    exponent = matched.group("exponent")
    if exponent is not None and abs(int(exponent)) > _MAX_EXPONENT:
        raise KubernetesQuantityError("Kubernetes resource quantity exponent is outside its bounds")
    try:
        with localcontext(Context(prec=128, Emin=-256, Emax=256)):
            parsed: object = parse_quantity(value)
        if (
            not isinstance(parsed, Decimal)
            or not parsed.is_finite()
            or not 0 <= parsed <= MAX_RESOURCE_QUANTITY
        ):
            raise KubernetesQuantityError("Kubernetes resource quantity is outside its bounds")
        return parsed
    except (DecimalException, ValueError):
        raise KubernetesQuantityError(
            "Kubernetes resource quantity cannot be represented"
        ) from None


def cpu_millicores(value: object) -> int:
    """Round a CPU quantity up to integer millicores without a binary float conversion."""
    return _integer_units(value, scale=1000)


def storage_bytes(value: object) -> int:
    """Round a memory or storage quantity up to integer bytes, never undercounting a request."""
    return _integer_units(value, scale=1)


def _integer_units(value: object, *, scale: int) -> int:
    parsed = parse_resource_quantity(value)
    with localcontext(Context(prec=128, Emin=-256, Emax=256)):
        result = int((parsed * scale).to_integral_value(rounding=ROUND_CEILING))
    if result > MAX_RESOURCE_QUANTITY:
        raise KubernetesQuantityError("Kubernetes resource accounting units exceed their bound")
    return result
