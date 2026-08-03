"""Deterministic read-model tools for cross-screen Command Deck questions."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Final, Literal, cast

from fdai.agents import PANTHEON_NAMES
from fdai.delivery.operator_api.read_model import ConsoleReadModel
from fdai.delivery.operator_api.routes.chat_turn_plan import TurnTool
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

    def turn_tools(self) -> tuple[TurnTool, ...]:
        """Return the structured capabilities backed by this resolver."""

        tools = [
            TurnTool(
                name="list_incidents",
                description="Read incident summaries by lifecycle status.",
                side_effect_class="read",
                argument_schema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "resolved", "all"],
                        },
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            ),
            TurnTool(
                name="list_hil",
                description="Read pending human approvals.",
                side_effect_class="read",
                argument_schema=_limit_schema(),
            ),
            TurnTool(
                name="query_audit",
                description="Read recent append-only audit records.",
                side_effect_class="read",
                argument_schema=_limit_schema(),
            ),
            TurnTool(
                name="get_kpi",
                description="Read current dashboard metrics and trust-tier distribution.",
                side_effect_class="read",
                argument_schema={"type": "object", "additionalProperties": False},
            ),
        ]
        if self.conversation_search is not None:
            tools.append(
                TurnTool(
                    name="search_conversations",
                    description="Search this principal's prior conversations.",
                    side_effect_class="read",
                    argument_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string", "maxLength": 500}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                )
            )
        return tuple(tools)

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        """Execute one validated read plan without reclassifying natural language."""

        if tool_name == "list_incidents":
            _reject_unknown_arguments(arguments, {"status", "limit"})
            status = _incident_status(arguments)
            limit = _limit_argument(arguments)
            incident_page = await self.read_model.list_incidents(
                status=status,
                limit=limit,
                cursor=None,
            )
            return {
                "tool": tool_name,
                "authority": "server_read_model",
                "result": incident_page.to_dict(),
            }
        if tool_name == "list_hil":
            _reject_unknown_arguments(arguments, {"limit"})
            hil_page = await self.read_model.list_hil_queue(limit=_limit_argument(arguments))
            return {
                "tool": tool_name,
                "authority": "server_read_model",
                "result": _safe_hil_page(hil_page.to_dict()),
            }
        if tool_name == "query_audit":
            _reject_unknown_arguments(arguments, {"limit"})
            audit_page = await self.read_model.list_audit(limit=_limit_argument(arguments))
            return {
                "tool": tool_name,
                "authority": "server_read_model",
                "result": _safe_audit_page(audit_page.to_dict()),
            }
        if tool_name == "get_kpi":
            _reject_unknown_arguments(arguments, set())
            metrics = await self.read_model.dashboard_metrics()
            return {
                "tool": tool_name,
                "authority": "server_read_model",
                "result": _safe_kpi(metrics.to_dict()),
            }
        if tool_name == "search_conversations" and self.conversation_search is not None:
            _reject_unknown_arguments(arguments, {"query"})
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                raise ValueError("planned conversation query is invalid")
            conversation_page = await self.conversation_search.search(
                scope=ConversationSearchScope(principal_id=principal_id),
                query=ConversationSearchQuery(text=query.strip()),
            )
            payload = asdict(conversation_page)
            payload.pop("query_ms", None)
            payload["trusted"] = False
            return {
                "tool": tool_name,
                "authority": "server_conversation_search",
                "result": payload,
            }
        return None

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
                "result": _safe_hil_page(hil_page.to_dict()),
            }
        if _AUDIT.search(prompt):
            audit_page = await self.read_model.list_audit(limit=20)
            return {
                "tool": "query_audit",
                "authority": "server_read_model",
                "result": _safe_audit_page(audit_page.to_dict()),
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
                "result": _safe_kpi(metrics.to_dict()),
            }
        return None


def render_read_model_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    tool = evidence.get("tool")
    result = evidence.get("result")
    if not isinstance(tool, str) or not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if tool == "list_hil":
        total = _integer(result.get("total"))
        return (
            f"현재 pending 사람 승인은 {total}개입니다. 세부 내용은 Approver 권한 "
            "surface에서만 확인할 수 있습니다."
            if korean
            else (
                f"There are {total} pending human approval(s). Details are available only "
                "on an Approver-authorized surface."
            )
        )
    if tool == "query_audit":
        items = [item for item in result.get("items", []) if isinstance(item, Mapping)]
        heading = "최근 bounded audit 기록:" if korean else "Recent bounded audit records:"
        lines = [
            f"- {_integer(item.get('seq'))}: {_text(item.get('action_kind'))}, "
            f"{_text(item.get('mode'))}, {_text(item.get('recorded_at'))}"
            for item in items[:20]
        ]
        return f"{heading}\n" + ("\n".join(lines) if lines else "- none")
    if tool == "list_incidents":
        items = [item for item in result.get("items", []) if isinstance(item, Mapping)]
        heading = "최근 incident 요약:" if korean else "Recent incident summaries:"
        lines = [
            f"- {_text(item.get('correlation_id'))}: {_text(item.get('title'))}, "
            f"{_text(item.get('status'))}, {_text(item.get('severity'))}"
            for item in items[:20]
        ]
        return f"{heading}\n" + ("\n".join(lines) if lines else "- none")
    if tool == "get_kpi":
        events = _integer(result.get("event_count"))
        pending = _integer(result.get("hil_pending"))
        shadow = result.get("shadow_share")
        enforce = result.get("enforce_share")
        return (
            f"현재 event는 {events}개, pending 사람 승인은 {pending}개, shadow share는 "
            f"{shadow}, enforce share는 {enforce}입니다."
            if korean
            else (
                f"Current events: {events}; pending human approvals: {pending}; "
                f"shadow share: {shadow}; enforce share: {enforce}."
            )
        )
    return None


def read_model_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    tool = evidence.get("tool")
    result = evidence.get("result")
    if not isinstance(tool, str) or not isinstance(result, Mapping):
        return ()
    if tool == "query_audit":
        return tuple(
            f"audit:{_text(item.get('correlation_id'))}:{_integer(item.get('seq'))}"
            for item in result.get("items", [])
            if isinstance(item, Mapping) and _integer(item.get("seq")) > 0
        )
    if tool == "list_incidents":
        return tuple(
            f"incident:{_text(item.get('correlation_id'))}"
            for item in result.get("items", [])
            if isinstance(item, Mapping) and _text(item.get("correlation_id")) != "unknown"
        )
    return (f"read-model:{tool}",)


def _safe_hil_page(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {"total": _integer(payload.get("total")), "details_redacted": True}


def _safe_audit_page(payload: Mapping[str, Any]) -> dict[str, Any]:
    items = [item for item in payload.get("items", []) if isinstance(item, Mapping)]
    return {
        "items": [
            {
                "seq": item.get("seq"),
                "correlation_id": item.get("correlation_id"),
                "action_kind": item.get("action_kind"),
                "mode": item.get("mode"),
                "recorded_at": item.get("recorded_at"),
            }
            for item in items[:20]
        ],
        "next_cursor": payload.get("next_cursor"),
    }


def _safe_kpi(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("event_count", "shadow_share", "enforce_share", "hil_pending", "last_recorded_at")
    return {key: payload.get(key) for key in keys}


def _integer(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(value: object) -> str:
    return " ".join(value.split())[:512] if isinstance(value, str) and value.strip() else "unknown"


def _limit_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
        "additionalProperties": False,
    }


def _reject_unknown_arguments(arguments: Mapping[str, object], allowed: set[str]) -> None:
    if any(key not in allowed for key in arguments):
        raise ValueError("planned tool arguments contain unsupported fields")


def _limit_argument(arguments: Mapping[str, object]) -> int:
    value = arguments.get("limit", 20)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
        raise ValueError("planned tool limit is invalid")
    return value


def _incident_status(
    arguments: Mapping[str, object],
) -> Literal["active", "resolved", "all"]:
    value = arguments.get("status", "all")
    if value not in {"active", "resolved", "all"}:
        raise ValueError("planned tool status is invalid")
    return cast(Literal["active", "resolved", "all"], value)


__all__ = ["ReadModelChatTools", "read_model_evidence_refs", "render_read_model_answer"]
