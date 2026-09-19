"""Shared quantity accounting is exact, bounded and independent of ambient Decimal settings."""

from decimal import Decimal, Inexact, localcontext

import pytest
from fdai.delivery.kubernetes_quantity import (
    MAX_RESOURCE_QUANTITY,
    KubernetesQuantityError,
    cpu_millicores,
    parse_resource_quantity,
    storage_bytes,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "0"),
        (4, "4"),
        ("100m", "0.1"),
        ("2500u", "0.0025"),
        ("10n", "0.00000001"),
        ("1Ki", "1024"),
        ("128Mi", "134217728"),
        ("1.5Gi", "1610612736"),
        ("1Ti", "1099511627776"),
        ("1Pi", "1125899906842624"),
        ("1Ei", "1152921504606846976"),
        ("1k", "1000"),
        ("1M", "1000000"),
        ("1G", "1000000000"),
        ("1T", "1000000000000"),
        ("1P", "1000000000000000"),
        ("1E", "1000000000000000000"),
        ("1e3", "1000"),
        ("1E-3", "0.001"),
        (".5", "0.5"),
        ("1.", "1"),
        ("+2", "2"),
        ("1e-64", "1e-64"),
        (str(MAX_RESOURCE_QUANTITY), str(MAX_RESOURCE_QUANTITY)),
    ],
)
def test_quantity_base_units(value, expected) -> None:
    assert parse_resource_quantity(value) == Decimal(expected)


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        1.0,
        Decimal("1"),
        [],
        {},
        "",
        " 1",
        "1 ",
        "1\n",
        "1_000",
        "NaN",
        "Infinity",
        "-1",
        "-0",
        "１",
        "1K",
        "1ki",
        "1mi",
        "1mKi",
        "1e3Mi",
        "1e",
        "1e+",
        "1e1000000",
        "1e-65",
        "1e65",
        "9" * 97,
        "8Ei",
        MAX_RESOURCE_QUANTITY + 1,
        "9223372036854775808",
        -1,
    ],
)
def test_invalid_quantity_never_becomes_zero(value) -> None:
    with pytest.raises(KubernetesQuantityError):
        parse_resource_quantity(value)


@pytest.mark.parametrize(
    "value,expected", [("100m", 100), ("1", 1000), ("1n", 1), ("0", 0), ("1.000001", 1001)]
)
def test_cpu_rounds_up_without_loss(value, expected) -> None:
    assert cpu_millicores(value) == expected


@pytest.mark.parametrize("value,expected", [("1Gi", 1073741824), ("400m", 1), ("0", 0), ("1.1", 2)])
def test_memory_and_storage_round_up(value, expected) -> None:
    assert storage_bytes(value) == expected


def test_ambient_decimal_precision_and_traps_cannot_change_results() -> None:
    with localcontext() as active:
        active.prec = 2
        active.Emax = 2
        active.Emin = -2
        active.traps[Inexact] = True
        assert parse_resource_quantity("1.23456789Gi") == Decimal("1325607178.06043136")
        assert storage_bytes("1.23456789Gi") == 1325607179
        assert cpu_millicores("1.000001") == 1001
        assert active.prec == 2 and active.traps[Inexact]


def test_scaled_accounting_overflow_rejects() -> None:
    with pytest.raises(KubernetesQuantityError):
        cpu_millicores(MAX_RESOURCE_QUANTITY)


def test_long_coefficient_retains_every_digit() -> None:
    from fractions import Fraction

    coefficient = "1" * 90
    parsed = parse_resource_quantity("0." + coefficient + "Ki")
    assert Fraction(parsed) == Fraction(int(coefficient), 10**90) * 1024


@pytest.mark.parametrize("parsed", [1.0, Decimal("NaN"), Decimal("Infinity"), Decimal("-1")])
def test_library_return_value_is_checked(monkeypatch, parsed) -> None:
    monkeypatch.setattr("fdai.delivery.kubernetes_quantity.parse_quantity", lambda value: parsed)
    with pytest.raises(KubernetesQuantityError):
        parse_resource_quantity("1")


def test_library_decimal_error_is_sanitized(monkeypatch) -> None:
    from decimal import InvalidOperation

    def fail(value):
        raise InvalidOperation("synthetic-provider-detail")

    monkeypatch.setattr("fdai.delivery.kubernetes_quantity.parse_quantity", fail)
    with pytest.raises(KubernetesQuantityError) as failure:
        parse_resource_quantity("1")
    assert "synthetic-provider-detail" not in str(failure.value)
