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
    "|지표|티어 비율|shadow 비율|이벤트 수",
    re.IGNORECASE,
)
_HIL: Final = re.compile(
    r"\b(hil queue|pending approvals?|approval backlog|awaiting approval)\b"
    "|승인 대기|대기 중인 승인|승인 큐",
    re.IGNORECASE,
)
_AUDIT: Final = re.compile(
    r"\b(recent audit|latest audit|audit log|action history|execution history)\b"
    "|최근 감사|감사 로그"
    "|액션 이력|실행 이력",
    re.IGNORECASE,
)
_INCIDENTS: Final = re.compile(
    r"\b(list|show|how many)\s+(?:recent\s+|active\s+)?incidents?\b"
    "|인시던트 목록|인시던트 몇",
    re.IGNORECASE,
)
_CONVERSATION_SEARCH: Final = re.compile(
    r"^\s*(?:search[_\s-]?conversations?|conversation history|prior conversations)\s+(.*)$"
    r"|^\s*(?:대화 검색|이전 대화)\s+(.+)$",
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
