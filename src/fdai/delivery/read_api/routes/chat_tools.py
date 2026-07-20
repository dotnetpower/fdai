"""Deterministic read-model tools for cross-screen Command Deck questions."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Final

from fdai.agents import PANTHEON_NAMES
from fdai.delivery.read_api.read_model import ConsoleReadModel
from fdai.shared.providers.conversation_search import (
    ConversationSearch,
    ConversationSearchQuery,
    ConversationSearchScope,
)

_AGENT_TOKEN: Final = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

_KPI: Final = re.compile(
    r"\b(kpi|dashboard metrics?|tier mix|shadow share|enforce share|event count)\b"
    "|\uc9c0\ud45c|\ud2f0\uc5b4 \ube44\uc728|shadow \ube44\uc728|\uc774\ubca4\ud2b8 \uc218",
    re.IGNORECASE,
)
_HIL: Final = re.compile(
    r"\b(hil queue|pending approvals?|approval backlog|awaiting approval)\b"
    "|\uc2b9\uc778 \ub300\uae30|\ub300\uae30 \uc911\uc778 \uc2b9\uc778|\uc2b9\uc778 \ud050",
    re.IGNORECASE,
)
_AUDIT: Final = re.compile(
    r"\b(recent audit|latest audit|audit log|action history|execution history)\b"
    "|\ucd5c\uadfc \uac10\uc0ac|\uac10\uc0ac \ub85c\uadf8"
    "|\uc561\uc158 \uc774\ub825|\uc2e4\ud589 \uc774\ub825",
    re.IGNORECASE,
)
_INCIDENTS: Final = re.compile(
    r"\b(list|show|how many)\s+(?:recent\s+|active\s+)?incidents?\b"
    "|\uc778\uc2dc\ub358\ud2b8 \ubaa9\ub85d|\uc778\uc2dc\ub358\ud2b8 \uba87",
    re.IGNORECASE,
)
_CONVERSATION_SEARCH: Final = re.compile(
    r"^\s*(?:search[_\s-]?conversations?|conversation history|prior conversations)\s+(.*)$"
    "|^\s*(?:\ub300\ud654 \uac80\uc0c9|\uc774\uc804 \ub300\ud654)\s+(.+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReadModelChatTools:
    """Resolve direct read intents against the console's authoritative view."""

    read_model: ConsoleReadModel
    conversation_search: ConversationSearch | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        named_agents = {name.lower() for name in PANTHEON_NAMES}
        if any(token.lower() in named_agents for token in _AGENT_TOKEN.findall(prompt)):
            return None
        search_match = _CONVERSATION_SEARCH.match(prompt)
        if search_match is not None and self.conversation_search is not None:
            query_text = next(
                (group.strip() for group in search_match.groups() if group and group.strip()),
                "",
            )
            if not query_text:
                return None
            page = await self.conversation_search.search(
                scope=ConversationSearchScope(principal_id=principal_id),
                query=ConversationSearchQuery(text=query_text),
            )
            payload = asdict(page)
            payload.pop("query_ms", None)
            payload["trusted"] = False
            return {
                "tool": "search_conversations",
                "authority": "server_conversation_search",
                "result": payload,
            }
        if _HIL.search(prompt):
            hil_page = await self.read_model.list_hil_queue(limit=20)
            return {
                "tool": "list_hil",
                "authority": "server_read_model",
                "result": hil_page.to_dict(),
            }
        if _AUDIT.search(prompt):
            audit_page = await self.read_model.list_audit(limit=20)
            return {
                "tool": "query_audit",
                "authority": "server_read_model",
                "result": audit_page.to_dict(),
            }
        if _INCIDENTS.search(prompt):
            incident_page = await self.read_model.list_incidents(
                status="all", limit=20, cursor=None
            )
            return {
                "tool": "list_incidents",
                "authority": "server_read_model",
                "result": incident_page.to_dict(),
            }
        if _KPI.search(prompt):
            metrics = await self.read_model.dashboard_metrics()
            return {
                "tool": "get_kpi",
                "authority": "server_read_model",
                "result": metrics.to_dict(),
            }
        return None


__all__ = ["ReadModelChatTools"]
