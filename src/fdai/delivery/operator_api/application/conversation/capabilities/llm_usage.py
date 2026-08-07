"""Deterministic LLM usage evidence for operator conversations."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from fdai.core.metering.aggregate import (
    summarize_by_day,
    summarize_by_mode,
    summarize_by_model,
    summarize_by_scope,
    summarize_total,
    usage_summaries_as_mapping,
)
from fdai.core.metering.records import InvocationScope
from fdai.core.metering.sink import MeteringReader
from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    ChatToolResolver,
)
from fdai.delivery.operator_api.application.conversation.turn_plan import TurnTool
from fdai.delivery.operator_api.projections.conversation.terminal import (
    parse_llm_usage_analysis_context,
)

_EXPLICIT_USAGE: Final = re.compile(
    r"\b(?:llm|model|token)\b.{0,32}\b(?:usage|consumption|tokens?|calls?)\b|"
    r"\b(?:usage|consumption)\b.{0,32}\b(?:llm|model|token)\b|"
    r"(?:LLM|모델|토큰).{0,24}(?:사용량|소모량|호출량)|"
    r"(?:사용량|소모량|호출량).{0,24}(?:LLM|모델|토큰)",
    re.IGNORECASE,
)
_FOLLOWUP_CUE: Final = re.compile(
    r"\b(?:last|past|previous|prior|this)\s+(?:day|week|month)|"
    r"\b(?:daily|weekly|monthly|hourly|again|trend|"
    r"chart|graph|table|export|download|group(?:ed)?\s+by)\b|"
    # `only` alone is a weak cue - exclude it right after "read", since
    # "read-only"/"read only" is FDAI's own pervasive read-only-architecture
    # phrase and must never by itself imply an LLM-usage analysis follow-up.
    r"(?<!read[- ])\bonly\b|"
    r"(?:오늘|어제|최근|지난|이번).{0,12}(?:일|주|주간|달|월|개월)|"
    r"(?:일주일|한\s*주|하루|한\s*달|한\s*개월)|"
    r"(?:그래프|차트|표|테이블)(?:로|으로)?|"
    r"(?:모델|범위|모드|날짜|일자|월|대화|채팅)별|"
    r"(?:다시|그거|그것|같은\s*방식|추이|내보내기|다운로드|만\s*(?:보여|알려))",
    re.IGNORECASE,
)
_EXPLICIT_OTHER_SUBJECT: Final = re.compile(
    r"\b(?:vms?|virtual\s+machines?|inventory|database|postgres|sql|resource|subscription|"
    r"incident|service\s+health|resource\s+health|service\s+outage|outage|"
    r"cpu|memory|storage|network|image|photo|screenshot|attachment|document|file|"
    r"deployment|pod|cluster|aks|container\s+app|cost|spend|billing|error\s+rate|"
    r"latency|availability|throughput|request\s+count|success\s+rate|failure\s+rate)\b|"
    r"(?:가상\s*머신|인벤토리|데이터베이스|리소스|구독|인시던트|이미지|사진|스크린샷|첨부|문서|파일|"
    r"서비스\s*상태|"
    r"리소스\s*상태|장애|아웃티지|CPU|메모리|스토리지|네트워크|배포|파드|클러스터|AKS|"
    r"컨테이너\s*앱|비용|지출|청구|오류율|에러율|지연|가용성|처리량|요청\s*수|"
    r"성공률|실패율|장애\s*수|인시던트\s*수)",
    re.IGNORECASE,
)
_UNSUPPORTED_REFINEMENT: Final = re.compile(
    r"\b(?:compare|comparison|versus|vs\.?|export|download|csv|json)\b|"
    r"(?:비교|대비|내보내기|다운로드|CSV|JSON)",
    re.IGNORECASE,
)
_NUMBERED_WINDOW: Final = re.compile(
    r"\b(?:last|past|previous|recent)\s+(\d{1,3})\s*(days?|weeks?|months?)\b|"
    r"(?:최근|지난)\s*(\d{1,3})\s*(일|주|주간|개월|달)",
    re.IGNORECASE,
)
_SEVEN_DAYS: Final = re.compile(
    r"\b(?:last|past|previous)\s+(?:7\s+days?|week)\b|"
    r"(?:일주일|한\s*주|지난\s*주|최근\s*7\s*일)",
    re.IGNORECASE,
)
_THIRTY_DAYS: Final = re.compile(
    r"\b(?:last|past|previous)\s+(?:30\s+days?|month)\b|"
    r"(?:한\s*달|한\s*개월|지난\s*달|최근\s*30\s*일)",
    re.IGNORECASE,
)
_GROUP_MODEL: Final = re.compile(r"\b(?:by\s+model|per\s+model)\b|모델별", re.IGNORECASE)
_GROUP_SCOPE: Final = re.compile(r"\b(?:by\s+scope|per\s+scope)\b|범위별", re.IGNORECASE)
_GROUP_MODE: Final = re.compile(r"\b(?:by\s+mode|per\s+mode)\b|모드별", re.IGNORECASE)
_CHAT_ONLY: Final = re.compile(
    r"\b(?:chat|conversation)\s+only\b|(?:채팅|대화)(?:\s*만|.{0,12}사용량)",
    re.IGNORECASE,
)
_GROUPERS: Final = {
    "day": summarize_by_day,
    "model": summarize_by_model,
    "scope": summarize_by_scope,
    "mode": summarize_by_mode,
}
_MAX_LOOKBACK_DAYS = 90


def needs_llm_usage(prompt: str) -> bool:
    """Return whether the current turn explicitly requests measured LLM usage."""

    return bool(_EXPLICIT_USAGE.search(prompt))


def is_llm_usage_followup(prompt: str) -> bool:
    """Return whether an omitted-subject analysis refinement may reuse an anchor."""

    return bool(
        not needs_llm_usage(prompt)
        and _FOLLOWUP_CUE.search(prompt)
        and not _EXPLICIT_OTHER_SUBJECT.search(prompt)
    )


@dataclass(frozen=True, slots=True)
class LlmUsageQuery:
    group_by: str = "day"
    lookback_days: int = 30
    usage_scope: str | None = None

    def __post_init__(self) -> None:
        if self.group_by not in _GROUPERS:
            raise ValueError("LLM usage group_by is invalid")
        if not 1 <= self.lookback_days <= _MAX_LOOKBACK_DAYS:
            raise ValueError("LLM usage lookback_days MUST be between 1 and 90")
        if self.usage_scope not in {None, InvocationScope.OPERATOR_CHAT.value}:
            raise ValueError("LLM usage usage_scope is invalid")


@dataclass(frozen=True, slots=True)
class LlmUsageChatTools:
    """Read bounded measured token usage without estimating price or cost."""

    reader: MeteringReader
    fallback: ChatToolResolver | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def turn_tools(self) -> tuple[TurnTool, ...]:
        return (
            TurnTool(
                name="query_llm_usage",
                description=(
                    "Read measured LLM token usage by day, model, workload scope, or mode."
                ),
                side_effect_class="read",
                argument_schema={
                    "type": "object",
                    "properties": {
                        "group_by": {
                            "type": "string",
                            "enum": sorted(_GROUPERS),
                        },
                        "lookback_days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": _MAX_LOOKBACK_DAYS,
                        },
                        "usage_scope": {
                            "type": "string",
                            "enum": [InvocationScope.OPERATOR_CHAT.value],
                        },
                    },
                    "required": ["group_by", "lookback_days"],
                    "additionalProperties": False,
                },
            ),
        )

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_llm_usage(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        try:
            query = _query_from_prompt(prompt)
        except ValueError:
            return _invalid_query_evidence("lookback_out_of_range")
        return await self._query(query)

    async def resolve_planned(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        principal_id: str,
    ) -> dict[str, Any] | None:
        del principal_id
        if tool_name != "query_llm_usage":
            return None
        allowed = {"group_by", "lookback_days", "usage_scope"}
        if set(arguments) - allowed:
            raise ValueError("planned LLM usage arguments are invalid")
        group_by = arguments.get("group_by")
        lookback_days = arguments.get("lookback_days")
        usage_scope = arguments.get("usage_scope")
        if not isinstance(group_by, str) or not isinstance(lookback_days, int):
            raise ValueError("planned LLM usage arguments are invalid")
        if usage_scope is not None and not isinstance(usage_scope, str):
            raise ValueError("planned LLM usage arguments are invalid")
        return await self._query(
            LlmUsageQuery(
                group_by=group_by,
                lookback_days=lookback_days,
                usage_scope=usage_scope,
            )
        )

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        del principal_id
        anchor = _analysis_anchor(context)
        if (
            anchor is None
            or not is_llm_usage_followup(prompt)
            or _UNSUPPORTED_REFINEMENT.search(prompt)
        ):
            return None
        try:
            query = _refine_query(prompt, anchor)
        except ValueError:
            return None
        return await self._query(query)

    async def _query(self, query: LlmUsageQuery) -> dict[str, Any]:
        observed_at = self.now().astimezone(UTC)
        window_start = observed_at - timedelta(days=query.lookback_days)
        records = tuple(
            record
            for record in await self.reader.invocations()
            if window_start <= record.occurred_at.astimezone(UTC) < observed_at
            and (query.usage_scope is None or record.usage_scope.value == query.usage_scope)
        )
        grouped = _GROUPERS[query.group_by](records)
        result = {
            "status": "matched" if records else "none",
            "source": "metering",
            "observed_at": observed_at.isoformat(),
            "window_start": window_start.isoformat(),
            "window_end": observed_at.isoformat(),
            "group_by": query.group_by,
            "usage_scope": query.usage_scope,
            "total": dict(usage_summaries_as_mapping([summarize_total(records)])[0]),
            "rows": list(usage_summaries_as_mapping(grouped)),
            "record_count": len(records),
            "truncated": False,
            "evidence_refs": [
                f"metering:llm-usage@{window_start.isoformat()}/{observed_at.isoformat()}"
            ],
        }
        return {
            "tool": "query_llm_usage",
            "authority": "server_metering",
            "result": result,
            "analysis_context": _analysis_context(query),
        }


def _query_from_prompt(prompt: str) -> LlmUsageQuery:
    return LlmUsageQuery(
        group_by=_group_by(prompt),
        lookback_days=_lookback_days(prompt, default=30),
        usage_scope=(InvocationScope.OPERATOR_CHAT.value if _CHAT_ONLY.search(prompt) else None),
    )


def _refine_query(prompt: str, anchor: Mapping[str, object]) -> LlmUsageQuery:
    prior_group = anchor.get("group_by")
    prior_days = anchor.get("lookback_days")
    return LlmUsageQuery(
        group_by=_group_by(prompt, default=str(prior_group or "day")),
        lookback_days=_lookback_days(
            prompt,
            default=(prior_days if isinstance(prior_days, int) else 30),
        ),
        usage_scope=(
            InvocationScope.OPERATOR_CHAT.value
            if _CHAT_ONLY.search(prompt)
            or anchor.get("usage_scope") == InvocationScope.OPERATOR_CHAT.value
            else None
        ),
    )


def _group_by(prompt: str, *, default: str = "day") -> str:
    if _GROUP_MODEL.search(prompt):
        return "model"
    if _GROUP_SCOPE.search(prompt):
        return "scope"
    if _GROUP_MODE.search(prompt):
        return "mode"
    return "day" if re.search(r"그래프|차트|trend|chart|graph", prompt, re.IGNORECASE) else default


def _lookback_days(prompt: str, *, default: int) -> int:
    numbered = _NUMBERED_WINDOW.search(prompt)
    if numbered is not None:
        count = int(numbered.group(1) or numbered.group(3))
        unit = (numbered.group(2) or numbered.group(4) or "day").casefold()
        multiplier = (
            30
            if unit in {"month", "months", "개월", "달"}
            else 7
            if unit
            in {
                "week",
                "weeks",
                "주",
                "주간",
            }
            else 1
        )
        days = count * multiplier
        if not 1 <= days <= _MAX_LOOKBACK_DAYS:
            raise ValueError("LLM usage lookback is out of range")
        return days
    if _SEVEN_DAYS.search(prompt):
        return 7
    if _THIRTY_DAYS.search(prompt):
        return 30
    return default


def _analysis_context(query: LlmUsageQuery) -> dict[str, object]:
    return {
        "schema_version": 1,
        "domain": "llm_usage",
        "capability": "query_llm_usage",
        "measure": "total_tokens",
        "group_by": query.group_by,
        "lookback_days": query.lookback_days,
        "usage_scope": query.usage_scope,
    }


def _invalid_query_evidence(reason: str) -> dict[str, Any]:
    return {
        "tool": "query_llm_usage",
        "authority": "server_metering",
        "result": {"status": "unavailable", "reason": reason, "evidence_refs": []},
    }


def _analysis_anchor(context: Mapping[str, Any] | None) -> Mapping[str, object] | None:
    if context is None or context.get("status") not in {"verified", "corrected"}:
        return None
    return parse_llm_usage_analysis_context(context.get("analysis_context"))


__all__ = [
    "LlmUsageChatTools",
    "is_llm_usage_followup",
    "needs_llm_usage",
]
