"""Kubernetes quantity normalization tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fdai.delivery.kubernetes.quantity import (
    cpu_millicores,
    memory_bytes,
    parse_quantity,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("1", "1000m"),
        ("1Gi", "1024Mi"),
        ("1Mi", "1024Ki"),
        ("1e3", "1k"),
    ],
)
def test_parse_quantity_preserves_semantic_equivalence(left: str, right: str) -> None:
    assert parse_quantity(left) == parse_quantity(right)


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "1foo", "1 Mi", "--1"])
def test_parse_quantity_rejects_invalid_values(value: str) -> None:
    assert parse_quantity(value) is None


def test_metric_normalizers_preserve_existing_projection_units() -> None:
    assert cpu_millicores("925m") == 925.0
    assert cpu_millicores("250u") == 0.25
    assert cpu_millicores("1n") == 0.000001
    assert memory_bytes("128Mi") == 134_217_728
    assert memory_bytes("1Mi") == 1_048_576


@pytest.mark.parametrize(
    ("normalizer", "value", "message"),
    [
        (cpu_millicores, "1Gi", "invalid Kubernetes CPU quantity"),
        (cpu_millicores, "-1m", "invalid Kubernetes CPU quantity"),
        (memory_bytes, "1m", "invalid Kubernetes memory quantity"),
        (memory_bytes, "-1Mi", "invalid Kubernetes memory quantity"),
    ],
)
def test_metric_normalizers_reject_wrong_or_negative_units(
    normalizer: object,
    value: str,
    message: str,
) -> None:
    assert callable(normalizer)
    with pytest.raises(RuntimeError, match=message):
        normalizer(value)


def test_parse_quantity_returns_exact_decimal_base_units() -> None:
    assert parse_quantity("134947872440320m") == Decimal("134947872440.320")
