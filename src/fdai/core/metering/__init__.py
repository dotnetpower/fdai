"""LLM token + cost metering.

This package turns measured provider ``usage`` (prompt / completion
tokens) into per-conversation, per-day, and per-month cost views. It is
pure domain plus DI seams:

- :mod:`~fdai.core.metering.usage` - :class:`TokenUsage` value object.
- :mod:`~fdai.core.metering.pricing` - config-driven :class:`ModelPricing`
  / :class:`PricingTable` and cost computation.
- :mod:`~fdai.core.metering.records` - :class:`LlmInvocation`, the
  append-only metering unit.
- :mod:`~fdai.core.metering.aggregate` - pure rollups into
  :class:`UsageSummary` groups.
- :mod:`~fdai.core.metering.sink` - :class:`MeteringSink` /
  :class:`MeteringReader` seams and the in-memory default.

Prices are configuration (``rule-catalog/llm-pricing.yaml``), never code;
cost is :class:`decimal.Decimal` so monthly rollups do not drift.
"""

from __future__ import annotations

from fdai.core.metering.aggregate import (
    UsageSummary,
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_mode,
    summarize_by_month,
    summarize_total,
)
from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.pricing import ModelPricing, PricingTable
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink, MeteringReader, MeteringSink
from fdai.core.metering.usage import TokenUsage

__all__ = [
    "InMemoryMeteringSink",
    "InvocationMode",
    "LlmInvocation",
    "MeteringEmitter",
    "MeteringReader",
    "MeteringSink",
    "ModelPricing",
    "PricingTable",
    "TokenUsage",
    "UsageSummary",
    "summaries_as_mapping",
    "summarize_by_conversation",
    "summarize_by_day",
    "summarize_by_mode",
    "summarize_by_month",
    "summarize_total",
]
