"""Kubernetes resource quantity normalization for operational evidence."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Final

_QUANTITY: Final = re.compile(
    r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"(n|u|m|k|K|M|G|T|P|E|Ki|Mi|Gi|Ti|Pi|Ei)?$"
)
_MULTIPLIERS: Final = {
    "": Decimal(1),
    "n": Decimal("0.000000001"),
    "u": Decimal("0.000001"),
    "m": Decimal("0.001"),
    "k": Decimal(1_000),
    "K": Decimal(1_000),
    "M": Decimal(1_000_000),
    "G": Decimal(1_000_000_000),
    "T": Decimal(1_000_000_000_000),
    "P": Decimal(1_000_000_000_000_000),
    "E": Decimal(1_000_000_000_000_000_000),
    "Ki": Decimal(1_024),
    "Mi": Decimal(1_024**2),
    "Gi": Decimal(1_024**3),
    "Ti": Decimal(1_024**4),
    "Pi": Decimal(1_024**5),
    "Ei": Decimal(1_024**6),
}
_CPU_SUFFIXES: Final = frozenset({"", "n", "u", "m"})
_MEMORY_SUFFIXES: Final = frozenset({"", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei"})


def parse_quantity(value: str) -> Decimal | None:
    """Return a Kubernetes quantity in base units, or ``None`` when invalid."""

    parsed = _parse(value)
    return parsed[0] if parsed is not None else None


def cpu_millicores(value: object) -> float:
    """Normalize a Kubernetes CPU usage quantity to millicores."""

    parsed = _parse(value) if isinstance(value, str) else None
    if parsed is None or parsed[0] < 0 or parsed[1] not in _CPU_SUFFIXES:
        raise RuntimeError("kubectl returned an invalid Kubernetes CPU quantity")
    return float(parsed[0] * 1_000)


def memory_bytes(value: object) -> int:
    """Normalize a Kubernetes memory usage quantity to bytes."""

    parsed = _parse(value) if isinstance(value, str) else None
    if parsed is None or parsed[0] < 0 or parsed[1] not in _MEMORY_SUFFIXES:
        raise RuntimeError("kubectl returned an invalid Kubernetes memory quantity")
    return int(parsed[0])


def _parse(value: str) -> tuple[Decimal, str] | None:
    match = _QUANTITY.fullmatch(value)
    if match is None:
        return None
    suffix = match.group(2) or ""
    try:
        quantity = Decimal(match.group(1)) * _MULTIPLIERS[suffix]
    except (InvalidOperation, KeyError):
        return None
    return (quantity, suffix) if quantity.is_finite() else None


__all__ = ["cpu_millicores", "memory_bytes", "parse_quantity"]
