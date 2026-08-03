"""Bounded server-evidence freshness context for conversational follow-ups."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

_FRESHNESS_FOLLOWUP: Final = re.compile(
    r"\b(?:oldest|earliest|stale)\b.{0,64}\b(?:data|evidence|observation)\b|"
    r"\bwhich evidence is stale\b|"
    r"(?:가장\s*오래된|제일\s*오래된|가장\s*이른).{0,32}(?:데이터|근거|관찰)",
    re.IGNORECASE,
)
_MAX_SOURCE_CHARS: Final = 512
_MAX_LOOKBACK_SECONDS: Final = 2_592_000
_MAX_FUTURE_SKEW: Final = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class EvidenceFreshnessContext:
    source: str
    observed_at: datetime
    window_start: datetime
    status: str
    truncated: bool

    def __post_init__(self) -> None:
        if not self.source.strip() or len(self.source) > _MAX_SOURCE_CHARS:
            raise ValueError("freshness context source MUST be bounded")
        if self.observed_at.tzinfo is None or self.window_start.tzinfo is None:
            raise ValueError("freshness context timestamps MUST be timezone-aware")
        if self.window_start > self.observed_at:
            raise ValueError("freshness context window_start MUST be <= observed_at")
        if self.observed_at > datetime.now(tz=UTC) + _MAX_FUTURE_SKEW:
            raise ValueError("freshness context observed_at MUST NOT be in the future")
        if self.status not in {"matched", "partial", "none", "unavailable"}:
            raise ValueError("freshness context status is unsupported")

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "observed_at": _timestamp(self.observed_at),
            "window_start": _timestamp(self.window_start),
            "status": self.status,
            "truncated": self.truncated,
        }


def parse_evidence_freshness_context(raw: object) -> EvidenceFreshnessContext | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("evidence_freshness_context MUST be an object")
    source = raw.get("source")
    observed_at = raw.get("observed_at")
    window_start = raw.get("window_start")
    status = raw.get("status")
    truncated = raw.get("truncated")
    if not all(isinstance(value, str) for value in (source, observed_at, window_start, status)):
        raise ValueError("evidence_freshness_context fields MUST be strings")
    if not isinstance(truncated, bool):
        raise ValueError("evidence_freshness_context.truncated MUST be boolean")
    return EvidenceFreshnessContext(
        source=str(source),
        observed_at=_parse_timestamp(str(observed_at)),
        window_start=_parse_timestamp(str(window_start)),
        status=str(status),
        truncated=truncated,
    )


def needs_evidence_freshness_context(prompt: str) -> bool:
    return _FRESHNESS_FOLLOWUP.search(prompt) is not None


def response_evidence_freshness_context(
    view_context: Mapping[str, Any],
    fallback: EvidenceFreshnessContext | None = None,
) -> EvidenceFreshnessContext | None:
    tool = view_context.get("_tool_evidence")
    result = tool.get("result") if isinstance(tool, Mapping) else None
    query = tool.get("query") if isinstance(tool, Mapping) else None
    if not isinstance(result, Mapping):
        operational = view_context.get("_operational_evidence")
        if not isinstance(operational, Mapping) or operational.get("status") != "matched":
            return fallback
        result = operational
        query = None
    source = result.get("source")
    observed_raw = result.get("observed_at") or result.get("snapshot_at")
    status = result.get("status")
    if (
        not isinstance(source, str)
        or not isinstance(observed_raw, str)
        or not isinstance(status, str)
    ):
        return fallback
    try:
        observed_at = _parse_timestamp(observed_raw)
    except ValueError:
        return fallback
    window_start_raw = result.get("window_start")
    if isinstance(window_start_raw, str):
        try:
            window_start = _parse_timestamp(window_start_raw)
        except ValueError:
            return fallback
    else:
        lookback_seconds = query.get("lookback_seconds") if isinstance(query, Mapping) else None
        if not isinstance(lookback_seconds, int) or isinstance(lookback_seconds, bool):
            lookback_seconds = 0
        lookback_seconds = max(0, min(lookback_seconds, _MAX_LOOKBACK_SECONDS))
        window_start = observed_at - timedelta(seconds=lookback_seconds)
    try:
        return EvidenceFreshnessContext(
            source=source,
            observed_at=observed_at,
            window_start=window_start,
            status=status,
            truncated=result.get("truncated") is True,
        )
    except ValueError:
        return fallback


def render_evidence_freshness_answer(
    prompt: str,
    context: EvidenceFreshnessContext | None,
    *,
    locale: str | None = None,
) -> str | None:
    if context is None or not needs_evidence_freshness_context(prompt):
        return None
    korean = bool(
        locale.casefold().startswith("ko") if locale is not None else re.search(r"[가-힣]", prompt)
    )
    observed = _timestamp(context.observed_at)
    oldest = _timestamp(context.window_start)
    limited = context.status == "partial" or context.truncated
    if korean:
        limitation = (
            " 근거가 partial 또는 truncated 상태이므로 더 오래된 데이터가 제외되었을 수 있습니다."
            if limited
            else ""
        )
        return (
            f"이전 답변에 사용한 가장 오래된 데이터 경계는 {oldest}입니다. "
            f"근거 source는 {context.source}, 관찰 시각은 {observed}, 상태는 "
            f"{context.status}입니다.{limitation} 이 값은 조회 window의 하한이며 실제로 반환된 "
            "가장 오래된 개별 record 시각과는 다를 수 있습니다."
        )
    limitation = (
        " The evidence was partial or truncated, so older data may have been excluded."
        if limited
        else ""
    )
    return (
        f"The oldest data boundary used by the prior answer was {oldest}. The source was "
        f"{context.source}, observed at {observed}, with status {context.status}.{limitation} "
        "This is the lower bound of the query window and may differ from the oldest individual "
        "record returned."
    )


def freshness_evidence_refs(context: EvidenceFreshnessContext) -> tuple[str, ...]:
    return (f"freshness:{context.source}@{_timestamp(context.observed_at)}",)


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("freshness context timestamp MUST be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("freshness context timestamp MUST be timezone-aware")
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
