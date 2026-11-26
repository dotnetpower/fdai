"""Config-driven LLM pricing and cost computation.

Prices are **configuration, never code** - per the safety rules in
``.github/instructions/coding-conventions.instructions.md`` a price is
loaded from catalog-as-code (``rule-catalog/llm-pricing.yaml``) at
startup, so a fork tunes rates (region, currency, negotiated discount)
without editing ``core/``. Money is represented as :class:`Decimal` to
avoid float rounding drift when thousands of small per-call costs are
summed into a monthly total.

Cost is computed against a ``model_key`` (the resolved model family or
capability id the adapter knows). When no price is configured for a key
the table returns ``None`` - the caller records the usage with an
unknown cost rather than guessing a number, mirroring the "abstain, do
not fabricate" invariant the quality gate uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from fdai.core.metering.usage import TokenUsage

_PER_1K: Final = Decimal(1000)


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """List price for one model, per 1,000 tokens.

    ``input_per_1k`` / ``output_per_1k`` are the currency amount charged
    per 1,000 prompt / completion tokens. ``currency`` is an ISO 4217
    code (informational; the control plane does not convert currencies).
    """

    input_per_1k: Decimal
    output_per_1k: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        # NaN / Infinity parse as valid Decimals and slip a plain ``< 0``
        # guard (``Decimal('NaN') < 0`` is False), so reject non-finite
        # first - a non-finite price would poison every cost sum.
        if not self.input_per_1k.is_finite():
            raise ValueError("input_per_1k MUST be a finite number")
        if not self.output_per_1k.is_finite():
            raise ValueError("output_per_1k MUST be a finite number")
        if self.input_per_1k < 0:
            raise ValueError("input_per_1k MUST be >= 0")
        if self.output_per_1k < 0:
            raise ValueError("output_per_1k MUST be >= 0")
        if not self.currency:
            raise ValueError("currency MUST NOT be empty")

    def cost_of(self, usage: TokenUsage) -> Decimal:
        """Cost of one usage at this price (exact :class:`Decimal`)."""
        return (
            self.input_per_1k * Decimal(usage.prompt_tokens)
            + self.output_per_1k * Decimal(usage.completion_tokens)
        ) / _PER_1K


@dataclass(frozen=True, slots=True)
class PricingTable:
    """Immutable lookup of ``model_key -> ModelPricing``."""

    _by_key: Mapping[str, ModelPricing]

    def pricing_for(self, model_key: str) -> ModelPricing | None:
        """Return the price for ``model_key`` or ``None`` when unpriced."""
        return self._by_key.get(model_key)

    def cost_of(self, *, model_key: str, usage: TokenUsage) -> Decimal | None:
        """Cost of ``usage`` for ``model_key``; ``None`` when the key is unpriced."""
        pricing = self._by_key.get(model_key)
        if pricing is None:
            return None
        return pricing.cost_of(usage)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Mapping[str, object]]) -> PricingTable:
        """Build a table from a parsed config mapping.

        Each entry is ``model_key -> {input_per_1k, output_per_1k,
        currency?}``. Numeric fields are parsed via :class:`Decimal` from
        ``str`` / ``int`` / ``float`` (strings are preferred in the YAML
        so the exact decimal is preserved). Any malformed entry raises so
        an invalid price is caught at load time, not at bill time.
        """
        table: dict[str, ModelPricing] = {}
        for model_key, spec in raw.items():
            if not isinstance(model_key, str) or not model_key:
                raise ValueError("pricing key MUST be a non-empty string")
            if not isinstance(spec, Mapping):
                raise ValueError(f"pricing entry {model_key!r} MUST be a mapping")
            try:
                input_per_1k = _to_decimal(spec["input_per_1k"])
                output_per_1k = _to_decimal(spec["output_per_1k"])
            except KeyError as exc:
                raise ValueError(
                    f"pricing entry {model_key!r} MUST declare {exc.args[0]!r}"
                ) from exc
            currency_raw = spec.get("currency", "USD")
            if not isinstance(currency_raw, str) or not currency_raw:
                raise ValueError(f"pricing entry {model_key!r} currency MUST be a non-empty string")
            table[model_key] = ModelPricing(
                input_per_1k=input_per_1k,
                output_per_1k=output_per_1k,
                currency=currency_raw,
            )
        return cls(_by_key=table)


def _to_decimal(value: object) -> Decimal:
    """Parse a price field into a finite :class:`Decimal`, rejecting bad shapes."""
    if isinstance(value, bool):
        # bool subtypes int; a price is never a boolean.
        raise ValueError("price MUST be a number, not a boolean")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, (int, str)):
        try:
            parsed = Decimal(value)
        except Exception as exc:  # noqa: BLE001 - re-raised as ValueError below
            raise ValueError(f"price {value!r} is not a valid decimal") from exc
    elif isinstance(value, float):
        # Route floats through str so 0.15 does not become 0.1500000000...
        parsed = Decimal(str(value))
    else:
        raise ValueError(f"price MUST be a number or numeric string, got {type(value).__name__}")
    if not parsed.is_finite():
        # 'NaN' / 'Infinity' parse cleanly but are not valid prices.
        raise ValueError(f"price {value!r} MUST be finite (not NaN/Infinity)")
    return parsed


__all__ = ["ModelPricing", "PricingTable"]
