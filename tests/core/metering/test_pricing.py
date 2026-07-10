"""Tests for :mod:`fdai.core.metering.pricing`."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fdai.core.metering.pricing import ModelPricing, PricingTable
from fdai.core.metering.usage import TokenUsage


def test_model_pricing_cost_of_is_exact() -> None:
    pricing = ModelPricing(input_per_1k=Decimal("0.15"), output_per_1k=Decimal("0.60"))
    usage = TokenUsage(prompt_tokens=2000, completion_tokens=500)
    # 2000/1000 * 0.15 + 500/1000 * 0.60 = 0.30 + 0.30 = 0.60
    assert pricing.cost_of(usage) == Decimal("0.60")


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("input_per_1k", {"input_per_1k": Decimal("-1"), "output_per_1k": Decimal("0")}),
        ("output_per_1k", {"input_per_1k": Decimal("0"), "output_per_1k": Decimal("-1")}),
    ],
)
def test_model_pricing_rejects_negative(field: str, kwargs: dict[str, Decimal]) -> None:
    with pytest.raises(ValueError, match=field):
        ModelPricing(**kwargs)


def test_model_pricing_rejects_empty_currency() -> None:
    with pytest.raises(ValueError, match="currency"):
        ModelPricing(input_per_1k=Decimal("0"), output_per_1k=Decimal("0"), currency="")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_model_pricing_rejects_non_finite(bad: str) -> None:
    # NaN/Infinity parse as valid Decimals and slip a plain ``< 0`` guard.
    with pytest.raises(ValueError, match="finite"):
        ModelPricing(input_per_1k=Decimal(bad), output_per_1k=Decimal("0"))
    with pytest.raises(ValueError, match="finite"):
        ModelPricing(input_per_1k=Decimal("0"), output_per_1k=Decimal(bad))


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_from_mapping_rejects_non_finite(bad: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        PricingTable.from_mapping({"m": {"input_per_1k": bad, "output_per_1k": "1"}})


def test_pricing_table_from_mapping_and_cost() -> None:
    table = PricingTable.from_mapping(
        {
            "gpt-4o": {"input_per_1k": "2.50", "output_per_1k": "10.0", "currency": "USD"},
            "gpt-4o-mini": {"input_per_1k": 0.15, "output_per_1k": 0.60},
        }
    )
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=1000)
    assert table.cost_of(model_key="gpt-4o", usage=usage) == Decimal("12.50")
    mini = table.pricing_for("gpt-4o-mini")
    assert mini is not None and mini.currency == "USD"


def test_pricing_table_unpriced_returns_none() -> None:
    table = PricingTable.from_mapping({})
    usage = TokenUsage(prompt_tokens=10, completion_tokens=10)
    assert table.pricing_for("absent") is None
    assert table.cost_of(model_key="absent", usage=usage) is None


def test_float_price_routed_through_str() -> None:
    table = PricingTable.from_mapping(
        {"m": {"input_per_1k": 0.1, "output_per_1k": 0.2}}
    )
    pricing = table.pricing_for("m")
    assert pricing is not None
    # 0.1 via str(Decimal) is exact, not 0.1000000000000000055...
    assert pricing.input_per_1k == Decimal("0.1")


def test_decimal_price_passed_through() -> None:
    table = PricingTable.from_mapping(
        {"m": {"input_per_1k": Decimal("0.15"), "output_per_1k": Decimal("0.60")}}
    )
    pricing = table.pricing_for("m")
    assert pricing is not None
    assert pricing.input_per_1k == Decimal("0.15")
    assert pricing.output_per_1k == Decimal("0.60")


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ({"": {"input_per_1k": "1", "output_per_1k": "1"}}, "non-empty string"),
        ({"m": "not-a-mapping"}, "MUST be a mapping"),
        ({"m": {"output_per_1k": "1"}}, "input_per_1k"),
        ({"m": {"input_per_1k": "1"}}, "output_per_1k"),
        ({"m": {"input_per_1k": True, "output_per_1k": "1"}}, "boolean"),
        ({"m": {"input_per_1k": "x", "output_per_1k": "1"}}, "valid decimal"),
        ({"m": {"input_per_1k": [1], "output_per_1k": "1"}}, "number or numeric string"),
        ({"m": {"input_per_1k": "1", "output_per_1k": "1", "currency": ""}}, "currency"),
    ],
)
def test_from_mapping_rejects_malformed(raw: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        PricingTable.from_mapping(raw)  # type: ignore[arg-type]
