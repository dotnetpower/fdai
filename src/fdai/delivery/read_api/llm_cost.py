"""LLM cost read panel (``GET /kpi/llm-cost``).

Projects the metering stream into the three views an operator asks for:
**per conversation** (grouped by ``correlation_id``), **per day**, and
**per month**, plus a grand total. Every number is derived from measured
provider ``usage`` recorded by the T2 adapters via
:class:`~fdai.core.metering.emitter.MeteringEmitter` - never estimated.

This is a :class:`~fdai.delivery.read_api.panels.ReadPanel`, so it is
registered GET-only behind the same reader-role gate as the core routes
and exposes no mutating back-channel. It reads through a
:class:`~fdai.core.metering.sink.MeteringReader`; the upstream default
composition root wires the in-memory sink, a fork wires a durable one -
the panel code is identical either way.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from fdai.core.metering.aggregate import (
    UsageSummary,
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_mode,
    summarize_by_month,
    summarize_total,
)
from fdai.core.metering.sink import MeteringReader

# Query-string values selecting a single grouping; absent -> all groupings.
_GROUP_DAY = "day"
_GROUP_MONTH = "month"
_GROUP_CONVERSATION = "conversation"
_GROUPS: frozenset[str] = frozenset({_GROUP_DAY, _GROUP_MONTH, _GROUP_CONVERSATION})

# Default cap on the per-conversation table. Days and months are naturally
# bounded, but conversations grow without limit; the panel returns the
# costliest ``max_conversations`` and flags truncation rather than
# serialising an unbounded array.
_DEFAULT_MAX_CONVERSATIONS: int = 200


class LlmCostPanel:
    """Read-only per-conversation / daily / monthly LLM token + cost view."""

    def __init__(
        self,
        reader: MeteringReader,
        *,
        path: str = "/kpi/llm-cost",
        source: str = "metering",
        max_conversations: int = _DEFAULT_MAX_CONVERSATIONS,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError(f"LlmCostPanel path MUST start with '/', got {path!r}")
        if not source:
            raise ValueError("source MUST NOT be empty")
        if max_conversations < 1:
            raise ValueError("max_conversations MUST be >= 1")
        self._reader = reader
        self._path = path
        self._source = source
        self._max_conversations = max_conversations

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "llm-cost"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        """Return token + cost rollups.

        ``?group=day|month|conversation`` narrows the payload to one
        grouping; omitting it returns all three plus the grand total and a
        shadow-vs-enforce split. The numbers come straight from recorded
        usage, so the payload is honestly labelled with the injected
        ``source`` (``"metering"`` for a real store, e.g. ``"synthetic-dev"``
        in the dev harness). ``by_conversation`` is capped at
        ``max_conversations`` (costliest first) with a
        ``by_conversation_truncated`` flag.
        """
        records = await self._reader.invocations()
        total = summarize_total(records)
        payload: dict[str, Any] = {
            "source": self._source,
            "currency": total.currency,
            "invocations": total.invocations,
            "total": dict(summaries_as_mapping([total])[0]),
            "by_mode": list(summaries_as_mapping(summarize_by_mode(records))),
        }

        group = params.get("group")
        if group is not None and group not in _GROUPS:
            # Unknown filter: fail soft to the full payload rather than 500.
            group = None

        if group in (None, _GROUP_CONVERSATION):
            conversations = summarize_by_conversation(records)
            capped, truncated = _cap_conversations(conversations, self._max_conversations)
            payload["by_conversation"] = list(summaries_as_mapping(capped))
            payload["by_conversation_truncated"] = truncated
            payload["conversation_count"] = len(conversations)
        if group in (None, _GROUP_DAY):
            payload["by_day"] = list(summaries_as_mapping(summarize_by_day(records)))
        if group in (None, _GROUP_MONTH):
            payload["by_month"] = list(summaries_as_mapping(summarize_by_month(records)))
        return payload


def _cap_conversations(
    conversations: tuple[UsageSummary, ...], limit: int
) -> tuple[tuple[UsageSummary, ...], bool]:
    """Return the costliest ``limit`` conversations and whether truncation occurred.

    Ties on cost fall back to the correlation-id key so the ordering is
    deterministic across requests.
    """
    if len(conversations) <= limit:
        return conversations, False
    ranked = sorted(conversations, key=lambda s: (-_cost_or_zero(s.cost), s.key))
    return tuple(ranked[:limit]), True


def _cost_or_zero(cost: Decimal | None) -> Decimal:
    return cost if cost is not None else Decimal(0)


__all__ = ["LlmCostPanel"]
