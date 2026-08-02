"""Deterministic read-source provenance answers for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver
from fdai.delivery.operator_api.routes.data_sources import ReadDataSourceStatus

_READ_SOURCE_INTENT: Final = re.compile(
    r"\b(?:read|data|evidence)[\s_-]+sources?\b|데이터\s*소스|근거\s*소스",
    re.IGNORECASE,
)
_SOURCE_CODE_INTENT: Final = re.compile(
    r"\b(?:read|data|evidence)[\s_-]+sources?[\s_-]+code\b|소스\s*코드",
    re.IGNORECASE,
)
_DATABASE_MUTATION_INTENT: Final = re.compile(
    r"\b(?:create|delete|drop|truncate|insert|update|restart|scale|restore|backup)\b"
    r"|생성|삭제|지워|비워|추가|수정|재시작|스케일|복구|백업",
    re.IGNORECASE,
)
_NEGATED_DATABASE_MUTATION: Final = re.compile(
    r"\b(?:don't|do\s+not|never)\s+(?:create|delete|drop|truncate|insert|update|"
    r"restart|scale|restore|backup)\b"
    r"|(?:생성|삭제|지우|비우|추가|수정|재시작|스케일|복구|백업)하지\s*마"
    r"|지우지\s*마",
    re.IGNORECASE,
)
_DATABASE_READ_INTENT: Final = re.compile(
    r"\b(?:what|which|show|list|tell|enumerate)\b"
    r"|\bcontents?\s+please\b|\?|어떤|무슨|뭐|알려|보여|있어|있나|있을까|들었어|저장",
    re.IGNORECASE,
)
_DATABASE_CONTENT_INTENT: Final = re.compile(
    r"(?:\b(?:db|database|postgres(?:ql)?)\b.*"
    r"\b(?:what|which|data|information|items?|contents?|tables?|rows?|records?|contain|"
    r"holds?|stores?|stored?)\b)"
    r"|(?:\b(?:what|which|show|list|tell|enumerate)\b.*"
    r"\b(?:data|information|items?|contents?|tables?|rows?|records?|holds?|stores?|"
    r"stored?)\b.*"
    r"\b(?:db|database|postgres(?:ql)?)\b)"
    r"|(?:(?:what(?:'s|\s+is)|show\s+me\s+what(?:'s|\s+is)).*"
    r"(?:\bin\b|\binside\b|\b(?:stored|persisted)\s+in\b)\s+(?:the\s+)?"
    r"(?:(?:our|my|this)\s+)?"
    r"(?:db|database|postgres(?:ql)?)\b)"
    r"|(?:(?:db|디비|데이터베이스|postgres(?:ql)?)."
    r"*(?:어떤|무슨|뭐|데이터|정보|항목|내용|테이블|행|레코드)."
    r"*(?:있|들|저장))"
    r"|(?:(?:db|디비|데이터베이스|postgres(?:ql)?).*(?:들어|저장)."
    r"*(?:데이터|정보|항목|내용|테이블|행|레코드))"
    r"|(?:(?:db|디비|데이터베이스|postgres(?:ql)?).*(?:어떤|무슨|뭐)."
    r"*(?:데이터|정보|항목|내용|테이블|행|레코드))",
    re.IGNORECASE,
)
_MAX_SOURCES: Final = 40


@dataclass(frozen=True, slots=True)
class DataSourceChatTools:
    """Resolve provenance questions from the composition-owned manifest."""

    sources: tuple[ReadDataSourceStatus, ...]
    fallback: ChatToolResolver | None = None

    async def resolve(
        self,
        prompt: str,
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        if not needs_read_source_evidence(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        ordered = sorted(self.sources, key=lambda item: item.key)
        query_kind = (
            "source_manifest" if _READ_SOURCE_INTENT.search(prompt) else "database_contents"
        )
        selected = _select_sources(ordered, query_kind=query_kind)
        return {
            "tool": "describe_read_sources",
            "authority": "server_read_source_manifest",
            "result": {
                "status": "matched",
                "query_kind": query_kind,
                "total_sources": len(selected),
                "manifest_total_sources": len(ordered),
                "truncated": len(selected) > _MAX_SOURCES,
                "sources": [item.to_dict() for item in selected[:_MAX_SOURCES]],
            },
        }


def needs_read_source_evidence(prompt: str) -> bool:
    """Return whether a question asks what data the Operator API can substantiate."""

    normalized = " ".join(prompt.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").split())
    if _READ_SOURCE_INTENT.search(normalized):
        return not _SOURCE_CODE_INTENT.search(normalized)
    if not _DATABASE_CONTENT_INTENT.search(normalized) or not _DATABASE_READ_INTENT.search(
        normalized
    ):
        return False
    if _DATABASE_MUTATION_INTENT.search(normalized) and not _NEGATED_DATABASE_MUTATION.search(
        normalized
    ):
        return False
    return True


def render_read_source_answer(evidence: Mapping[str, Any], *, locale: str | None) -> str | None:
    """Render one source-manifest result without inferring database contents."""

    if evidence.get("tool") != "describe_read_sources":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return None
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list):
        return None
    sources = [item for item in raw_sources if isinstance(item, Mapping)]
    database_contents = result.get("query_kind") == "database_contents"
    korean = bool(locale and locale.casefold().startswith("ko"))
    if korean:
        lines = [
            _database_headline(sources, korean=True)
            if database_contents
            else "현재 Operator API composition이 선언한 데이터 근거는 다음과 같습니다."
        ]
        lines.extend(_source_lines(sources, korean=True))
        if result.get("truncated"):
            lines.append("Source 목록이 제한되어 일부 항목은 표시되지 않았습니다.")
        lines.append(
            "이 답변은 source manifest의 가용성, 지속성, 연결 route만 설명합니다. "
            "테이블이나 행을 직접 조회한 결과는 아닙니다."
        )
        return "\n".join(lines)

    lines = [
        _database_headline(sources, korean=False)
        if database_contents
        else "The Operator API composition declares these evidence sources:"
    ]
    lines.extend(_source_lines(sources, korean=False))
    if result.get("truncated"):
        lines.append("The source list was bounded, so some entries are not shown.")
    lines.append(
        "This answer describes source-manifest availability, durability, and connected routes. "
        "It does not inspect database tables or rows."
    )
    return "\n".join(lines)


def read_source_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable manifest references for terminal verification."""

    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    raw_sources = result.get("sources")
    if not isinstance(raw_sources, list):
        return ()
    return tuple(
        f"read-source:{item.get('key')}:{item.get('source')}:{item.get('availability')}"
        for item in raw_sources
        if isinstance(item, Mapping)
        and isinstance(item.get("key"), str)
        and isinstance(item.get("source"), str)
        and isinstance(item.get("availability"), str)
    )


def _select_sources(
    sources: list[ReadDataSourceStatus],
    *,
    query_kind: str,
) -> list[ReadDataSourceStatus]:
    if query_kind != "database_contents":
        return sources
    return [
        item
        for item in sources
        if item.key == "operational-state" or "postgres" in item.source.casefold()
    ]


def _database_headline(sources: list[Mapping[str, Any]], *, korean: bool) -> str:
    available = any(item.get("availability") == "available" for item in sources)
    if korean:
        return (
            "현재 Operator API에 연결된 운영 DB 데이터 근거는 다음과 같습니다."
            if available
            else "현재 Operator API에는 사용 가능한 운영 DB 데이터가 연결되어 있지 않습니다."
        )
    return (
        "The Operator API has these connected operational database evidence sources:"
        if available
        else "An available operational database is not connected to the Operator API."
    )


def _source_lines(sources: list[Mapping[str, Any]], *, korean: bool) -> list[str]:
    if not sources:
        return [
            "- 구성된 데이터 source가 없습니다." if korean else "- No data sources are configured."
        ]
    lines: list[str] = []
    for source in sources:
        key = str(source.get("key") or "unknown")
        provider = str(source.get("source") or "unknown")
        availability = str(source.get("availability") or "unknown")
        durable = source.get("durable")
        durable_label = "unknown" if durable is None else str(bool(durable)).lower()
        raw_routes = source.get("routes")
        routes = ", ".join(str(item) for item in raw_routes) if isinstance(raw_routes, list) else ""
        lines.append(
            f"- {key}: {availability}; source {provider}; durable {durable_label}; routes {routes}"
        )
    return lines


__all__ = [
    "DataSourceChatTools",
    "needs_read_source_evidence",
    "read_source_evidence_refs",
    "render_read_source_answer",
]
