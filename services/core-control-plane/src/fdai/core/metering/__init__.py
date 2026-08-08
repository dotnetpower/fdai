"""Measured LLM token metering with optional internal pricing.

This package records measured provider ``usage`` (prompt / completion
tokens) and projects token-only operator views. Optional pricing remains
available to internal budget controls. It is pure domain plus DI seams:

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
    invocations_as_mapping,
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_mode,
    summarize_by_model,
    summarize_by_month,
    summarize_by_scope,
    summarize_total,
    usage_summaries_as_mapping,
)
from fdai.core.metering.context import current_invocation_scope, with_invocation_scope
from fdai.core.metering.emitter import MeteringEmitter
from fdai.core.metering.pricing import ModelPricing, PricingTable
from fdai.core.metering.records import InvocationMode, InvocationScope, LlmInvocation
from fdai.core.metering.sink import InMemoryMeteringSink, MeteringReader, MeteringSink
from fdai.core.metering.usage import TokenUsage

__all__ = [
    "InMemoryMeteringSink",
    "InvocationMode",
    "InvocationScope",
    "LlmInvocation",
    "MeteringEmitter",
    "MeteringReader",
    "MeteringSink",
    "ModelPricing",
    "PricingTable",
    "TokenUsage",
    "UsageSummary",
    "current_invocation_scope",
    "invocations_as_mapping",
    "summaries_as_mapping",
    "summarize_by_conversation",
    "summarize_by_day",
    "summarize_by_model",
    "summarize_by_mode",
    "summarize_by_month",
    "summarize_by_scope",
    "summarize_total",
    "usage_summaries_as_mapping",
    "with_invocation_scope",
]
