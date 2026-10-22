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

import re
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


class InvocationDisposition(StrEnum):
    """Terminal outcome of the logical turn that owns this model call."""

    ANSWERED = "answered"
    HELD = "held"
    CLARIFICATION = "clarification"
    UNAVAILABLE = "unavailable"
    REGENERATED = "regenerated"
    UNKNOWN = "unknown"


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
    cached_prompt_tokens: int = 0
    duration_ms: int = 0
    profile_digest: str | None = None
    locale: str = "und"
    turn_family: str = "unknown"
    disposition: InvocationDisposition = InvocationDisposition.UNKNOWN

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
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
        if self.cached_prompt_tokens < 0 or self.cached_prompt_tokens > self.usage.prompt_tokens:
            raise ValueError("cached_prompt_tokens MUST be within measured prompt tokens")
        if self.duration_ms < 0:
            raise ValueError("duration_ms MUST NOT be negative")
        if (
            self.profile_digest is not None
            and re.fullmatch(r"sha256:[a-f0-9]{64}", self.profile_digest) is None
        ):
            raise ValueError("profile_digest MUST be one sha256 digest")
        for label, value in (("locale", self.locale), ("turn_family", self.turn_family)):
            if not value or len(value) > 64:
                raise ValueError(f"{label} MUST be non-empty and bounded")

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


__all__ = [
    "InvocationDisposition",
    "InvocationMode",
    "InvocationScope",
    "LlmInvocation",
]
