"""LLM usage read panel at the compatibility path ``GET /kpi/llm-cost``.

Projects the metering stream by workload scope, model, invocation,
conversation, day, and month. Every number is derived from measured
provider ``usage`` recorded by model adapters via
:class:`~fdai.core.metering.emitter.MeteringEmitter` - never estimated.

This is a :class:`~fdai.delivery.read_api.routes.panels.ReadPanel`, so it is
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
    invocations_as_mapping,
    summarize_by_conversation,
    summarize_by_day,
    summarize_by_mode,
    summarize_by_model,
    summarize_by_month,
    summarize_by_scope,
    summarize_total,
    usage_summaries_as_mapping,
)
from fdai.core.metering.records import InvocationScope
from fdai.core.metering.sink import MeteringReader

# Query-string values selecting a single grouping; absent -> all groupings.
_GROUP_DAY = "day"
_GROUP_MONTH = "month"
_GROUP_CONVERSATION = "conversation"
_GROUPS: frozenset[str] = frozenset({_GROUP_DAY, _GROUP_MONTH, _GROUP_CONVERSATION})

# Default caps for bounded read projections. Recent calls are the primary
# evidence surface; conversations keep deterministic correlation ordering.
_DEFAULT_MAX_CONVERSATIONS: int = 200
_DEFAULT_MAX_RECORDS: int = 500


class LlmCostPanel:
    """Read-only measured LLM token usage view."""

    def __init__(
        self,
        reader: MeteringReader,
        *,
        path: str = "/kpi/llm-cost",
        source: str = "metering",
        max_conversations: int = _DEFAULT_MAX_CONVERSATIONS,
        max_records: int = _DEFAULT_MAX_RECORDS,
    ) -> None:
        if not path.startswith("/"):
            raise ValueError(f"LlmCostPanel path MUST start with '/', got {path!r}")
        if not source:
            raise ValueError("source MUST NOT be empty")
        if max_conversations < 1:
            raise ValueError("max_conversations MUST be >= 1")
        if max_records < 1:
            raise ValueError("max_records MUST be >= 1")
        self._reader = reader
        self._path = path
        self._source = source
        self._max_conversations = max_conversations
        self._max_records = max_records

    @property
    def path(self) -> str:
        return self._path

    @property
    def name(self) -> str:
        return "llm-cost"

    async def render(self, *, params: Mapping[str, str]) -> Mapping[str, Any]:
        """Return measured token usage rollups and invocation facts.

        ``?group=day|month|conversation`` narrows the payload to one
        grouping; omitting it returns all three plus the grand total and a
        shadow-vs-enforce split. The numbers come straight from recorded
        usage, so the payload is honestly labelled with the injected
        ``source`` (``"metering"`` for a real store, e.g. ``"synthetic-dev"``
        in the dev harness). ``by_conversation`` is capped at
        ``max_conversations`` with a ``by_conversation_truncated`` flag.
        """
        records = await self._reader.invocations()
        total = summarize_total(records)
        chat_records = tuple(
            record for record in records if record.usage_scope is InvocationScope.OPERATOR_CHAT
        )
        recent_records = tuple(sorted(records, key=lambda record: record.occurred_at, reverse=True))
        visible_records = recent_records[: self._max_records]
        payload: dict[str, Any] = {
            "source": self._source,
            "latest_occurred_at": (
                max(record.occurred_at for record in records).isoformat() if records else None
            ),
            "invocations": total.invocations,
            "total": dict(usage_summaries_as_mapping([total])[0]),
            "chat": dict(
                usage_summaries_as_mapping(
                    [
                        next(
                            (
                                summary
                                for summary in summarize_by_scope(records)
                                if summary.key == "operator_chat"
                            ),
                            summarize_total(()),
                        )
                    ]
                )[0]
            ),
            "by_scope": list(usage_summaries_as_mapping(summarize_by_scope(records))),
            "by_model": list(usage_summaries_as_mapping(summarize_by_model(records))),
            "chat_by_model": list(usage_summaries_as_mapping(summarize_by_model(chat_records))),
            "by_mode": list(usage_summaries_as_mapping(summarize_by_mode(records))),
            "records": list(invocations_as_mapping(visible_records)),
            "records_truncated": len(visible_records) < len(recent_records),
            "record_count": len(recent_records),
        }

        group = params.get("group")
        if group is not None and group not in _GROUPS:
            # Unknown filter: fail soft to the full payload rather than 500.
            group = None

        if group in (None, _GROUP_CONVERSATION):
            conversations = summarize_by_conversation(records)
            capped = conversations[: self._max_conversations]
            payload["by_conversation"] = list(usage_summaries_as_mapping(capped))
            payload["by_conversation_truncated"] = len(capped) < len(conversations)
            payload["conversation_count"] = len(conversations)
        if group in (None, _GROUP_DAY):
            payload["by_day"] = list(usage_summaries_as_mapping(summarize_by_day(records)))
        if group in (None, _GROUP_MONTH):
            payload["by_month"] = list(usage_summaries_as_mapping(summarize_by_month(records)))
        return payload


__all__ = ["LlmCostPanel"]
