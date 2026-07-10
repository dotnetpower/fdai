"""Best-effort emitter that records one measured LLM invocation.

An LLM adapter holds a per-binding :class:`MeteringEmitter` (one
capability + model + tier) and calls :meth:`emit_safe` after a call
returns, handing it the measured :class:`TokenUsage`. The emitter binds
the current ``correlation_id`` (so the record rolls up per conversation),
computes cost from the injected :class:`PricingTable`, and appends to the
:class:`MeteringSink`.

Metering is a pure observability side-channel: :meth:`emit_safe` NEVER
raises into the caller's hot path. A backend hiccup is logged (with the
correlation id and full traceback) and swallowed there, so a failed
cost record can never break an autonomous decision. This is explicit
error handling, not a silent empty ``except``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from fdai.core.metering.pricing import PricingTable
from fdai.core.metering.records import InvocationMode, LlmInvocation
from fdai.core.metering.sink import MeteringSink
from fdai.core.metering.usage import TokenUsage
from fdai.shared.telemetry.correlation import current_correlation_id

_log = logging.getLogger(__name__)

# Catch-all bucket used when a usage record cannot be tied to a
# correlation id. Recording under this explicit, honest label keeps the
# daily / monthly totals whole instead of silently dropping real spend.
_UNCORRELATED: str = "uncorrelated"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MeteringEmitter:
    """Record one LLM invocation's usage + cost for a fixed capability binding."""

    def __init__(
        self,
        *,
        sink: MeteringSink,
        capability_id: str,
        model_key: str,
        tier: str,
        pricing: PricingTable | None = None,
        mode: InvocationMode = InvocationMode.ENFORCE,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not capability_id:
            raise ValueError("capability_id MUST NOT be empty")
        if not model_key:
            raise ValueError("model_key MUST NOT be empty")
        if not tier:
            raise ValueError("tier MUST NOT be empty")
        self._sink = sink
        self._capability_id = capability_id
        self._model_key = model_key
        self._tier = tier
        self._pricing = pricing
        self._mode = mode
        self._clock = clock or _utc_now
        # Warn-once latches so a misconfiguration is visible without
        # spamming a log line on every event.
        self._warned_unpriced = False
        self._warned_uncorrelated = False

    async def emit_safe(
        self, usage: TokenUsage, *, correlation_id: str | None = None
    ) -> None:
        """Record ``usage`` for the bound capability; never raise on failure.

        When no ``correlation_id`` is passed the emitter reads the one
        bound to the current context. If neither is available the record
        is filed under the explicit ``"uncorrelated"`` bucket (with a
        one-time warning) so the daily / monthly totals stay whole rather
        than silently losing real spend.
        """
        corr = correlation_id or current_correlation_id()
        if corr is None:
            corr = _UNCORRELATED
            if not self._warned_uncorrelated:
                self._warned_uncorrelated = True
                _log.warning(
                    "metering: no correlation id in context for capability_id=%s; "
                    "recording under the %r bucket",
                    self._capability_id,
                    _UNCORRELATED,
                )
        try:
            pricing_entry = (
                self._pricing.pricing_for(self._model_key)
                if self._pricing is not None
                else None
            )
            if (
                self._pricing is not None
                and pricing_entry is None
                and not self._warned_unpriced
            ):
                self._warned_unpriced = True
                _log.warning(
                    "metering: pricing table has no entry for model_key=%s "
                    "(capability_id=%s); recording usage with unknown cost",
                    self._model_key,
                    self._capability_id,
                )
            cost = pricing_entry.cost_of(usage) if pricing_entry is not None else None
            currency = pricing_entry.currency if pricing_entry is not None else None
            record = LlmInvocation(
                occurred_at=self._clock(),
                correlation_id=corr,
                capability_id=self._capability_id,
                model_key=self._model_key,
                tier=self._tier,
                mode=self._mode,
                usage=usage,
                cost=cost,
                currency=currency,
            )
            await self._sink.record(record)
        except Exception:
            _log.warning(
                "metering: failed to record invocation for correlation_id=%s "
                "capability_id=%s",
                corr,
                self._capability_id,
                exc_info=True,
            )


__all__ = ["MeteringEmitter"]
