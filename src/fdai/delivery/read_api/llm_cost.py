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
from typing import Any

from fdai.core.metering.aggregate import (
    summaries_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_month,
    summarize_total,
)
from fdai.core.metering.sink import MeteringReader

# Query-string values selecting a single grouping; absent -> all groupings.
_GROUP_DAY = "day"
_GROUP_MONTH = "month"
_GROUP_CONVERSATION = "conversation"
_GROUPS: frozenset[str] = frozenset({_GROUP_DAY, _GROUP_MONTH, _GROUP_CONVERSATION})


class LlmCostPanel:
    """Read-only per-conversation / daily / monthly LLM token + cost view."""

    def __init__(self, reader: MeteringReader, *, path: str = "/kpi/llm-cost") -> None:
        if not path.startswith("/"):
            raise ValueError(f"LlmCostPanel path MUST start with '/', got {path!r}")
        self._reader = reader
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "llm-cost"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        """Return token + cost rollups.

        ``?group=day|month|conversation`` narrows the payload to one
        grouping; omitting it returns all three plus the grand total. The
        numbers are measured, so the panel is honestly labelled
        ``source: "metering"`` (contrast the synthetic autonomy panel).
        """
        records = await self._reader.invocations()
        total = summarize_total(records)
        payload: dict[str, Any] = {
            "source": "metering",
            "currency": total.currency,
            "invocations": total.invocations,
            "total": dict(summaries_as_mapping([total])[0]),
        }

        group = params.get("group")
        if group is not None and group not in _GROUPS:
            # Unknown filter: fail soft to the full payload rather than 500.
            group = None

        if group in (None, _GROUP_CONVERSATION):
            payload["by_conversation"] = list(
                summaries_as_mapping(summarize_by_conversation(records))
            )
        if group in (None, _GROUP_DAY):
            payload["by_day"] = list(summaries_as_mapping(summarize_by_day(records)))
        if group in (None, _GROUP_MONTH):
            payload["by_month"] = list(summaries_as_mapping(summarize_by_month(records)))
        return payload


__all__ = ["LlmCostPanel"]
