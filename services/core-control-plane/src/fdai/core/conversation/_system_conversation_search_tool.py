"""Read-only narrator tool for access-scoped prior-conversation search."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import (
    SideEffectClass,
    ToolResult,
    _optional_int,
    _optional_str,
    _require_str,
)
from fdai.shared.providers.conversation_search import (
    ConversationSearch,
    ConversationSearchMode,
    ConversationSearchQuery,
    ConversationSearchScope,
)


class SearchConversationsTool:
    name = "search_conversations"
    description = "Search prior authorized conversation turns without an inference call."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, *, search: ConversationSearch) -> None:
        self._search = search

    async def call(
        self,
        *,
        arguments: Mapping[str, Any],
        principal: Principal,
    ) -> ToolResult:
        try:
            query_text = _require_str(arguments, "query")
            mode = ConversationSearchMode(_optional_str(arguments, "mode", default="terms"))
            query = ConversationSearchQuery(
                text=query_text,
                mode=mode,
                limit=_optional_int(
                    arguments,
                    "limit",
                    default=20,
                    minimum=1,
                    maximum=50,
                ),
                conversation_id=(_optional_str(arguments, "conversation_id", default="") or None),
                incident_id=_optional_str(arguments, "incident_id", default="") or None,
                correlation_id=(_optional_str(arguments, "correlation_id", default="") or None),
            )
            page = await self._search.search(
                scope=ConversationSearchScope(principal_id=principal.id),
                query=query,
            )
        except (TypeError, ValueError) as exc:
            return ToolResult(status="error", preview=str(exc))
        evidence_refs = tuple(dict.fromkeys(ref for hit in page.hits for ref in hit.evidence_refs))
        return ToolResult(
            status="ok",
            data={
                "trusted": False,
                "hits": [asdict(hit) for hit in page.hits],
                "result_cap": page.result_cap,
                "index_rows": page.index_rows,
            },
            preview=f"Found {len(page.hits)} authorized prior conversation turn(s).",
            evidence_refs=evidence_refs,
        )


__all__ = ["SearchConversationsTool"]
