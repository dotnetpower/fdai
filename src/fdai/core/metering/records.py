"""One recorded LLM invocation - the metering unit.

An :class:`LlmInvocation` is the append-only fact the metering sink
stores per model call: when it happened, which correlation (event or
operator conversation) it belongs to, the capability / model, the trust
tier, whether the run was ``shadow`` or ``enforce``, the measured token
usage, and the computed cost (``None`` when the model is unpriced).

It carries only machine-parseable, English, customer-agnostic fields so
it drops straight into the L0 audit stream. Grouping many of these by
``correlation_id`` yields the per-conversation cost; grouping by the day
or month bucket of ``occurred_at`` yields the daily / monthly cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from fdai.core.metering.usage import TokenUsage


class InvocationMode(StrEnum):
    """Whether the invocation ran in shadow (judge-only) or enforce mode."""

    SHADOW = "shadow"
    ENFORCE = "enforce"


class InvocationScope(StrEnum):
    """Operator-facing workload that caused an LLM invocation."""

    CONTROL_PLANE = "control_plane"
    OPERATOR_CHAT = "operator_chat"


@dataclass(frozen=True, slots=True)
class LlmInvocation:
    """A single measured LLM call, ready for cost rollups.

    ``correlation_id`` groups every model call of one logical unit - a
    T2 judgment invokes multiple models on the same event, and an
    operator conversation spans several turns; both roll up by this id
    into a single per-conversation cost.

    ``occurred_at`` MUST be timezone-aware so day / month bucketing is
    deterministic across processes; a naive datetime is rejected.
    ``cost`` is ``None`` when no price was configured for ``model_key``;
    ``currency`` is the ISO 4217 unit of ``cost`` (``None`` when unpriced)
    so a rollup never sums two currencies as if they were one.
    """

    occurred_at: datetime
    correlation_id: str
    capability_id: str
    model_key: str
    tier: str
    mode: InvocationMode
    usage: TokenUsage
    usage_scope: InvocationScope = InvocationScope.CONTROL_PLANE
    cost: Decimal | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at MUST be timezone-aware")
        if not self.correlation_id:
            raise ValueError("correlation_id MUST NOT be empty")
        if not self.capability_id:
            raise ValueError("capability_id MUST NOT be empty")
        if not self.model_key:
            raise ValueError("model_key MUST NOT be empty")
        if not self.tier:
            raise ValueError("tier MUST NOT be empty")
        if self.cost is not None and self.cost < 0:
            raise ValueError("cost MUST be >= 0 when present")
        if self.currency is not None and not self.currency:
            raise ValueError("currency MUST NOT be empty when present")

    @property
    def day_bucket(self) -> str:
        """UTC calendar day as ``YYYY-MM-DD``."""
        return self._utc().strftime("%Y-%m-%d")

    @property
    def month_bucket(self) -> str:
        """UTC calendar month as ``YYYY-MM``."""
        return self._utc().strftime("%Y-%m")

    def _utc(self) -> datetime:
        return self.occurred_at.astimezone(UTC)


__all__ = ["InvocationMode", "InvocationScope", "LlmInvocation"]
