"""Deterministic T2 proposer recovery evidence for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver

_RECOVERY_QUESTION: Final = re.compile(
    r"\bt2[_ .-]*proposer(?:[_ .-]*(?:error|failure|recovery))?\b|"
    r"t2[_ .-]*proposer[_ .-]*error:[A-Za-z][A-Za-z0-9_]*|"
    r"T2.{0,20}(?:proposer|제안).{0,20}(?:오류|실패|복구)",
    re.IGNORECASE,
)
_RECEIPT_PREFIX = "t2-recovery:receipt:"


class T2RecoveryStateReader(Protocol):
    async def read_states(self, prefix: str, *, limit: int) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class T2RecoveryChatTools:
    reader: T2RecoveryStateReader
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_t2_recovery_evidence(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        records = tuple(await self.reader.read_states(_RECEIPT_PREFIX, limit=100))
        result = _project_result(records)
        return {
            "tool": "query_t2_recovery",
            "authority": "server_t2_recovery_ledger",
            "result": result,
        }


def needs_t2_recovery_evidence(prompt: str) -> bool:
    return _RECOVERY_QUESTION.search(prompt) is not None


def _project_result(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"status": "none", "attempt_count": 0, "evidence_refs": []}
    latest = records[0]
    correlation_id = str(latest.get("correlation_id") or "")
    related = tuple(
        record for record in records if str(record.get("correlation_id") or "") == correlation_id
    )
    recovered = any(
        record.get("status") == "succeeded" and record.get("recovered") is True
        for record in related
    )
    terminal_failure = any(
        record.get("status") == "failed" and record.get("terminal") is True for record in related
    )
    state = "recovered" if recovered else "unavailable" if terminal_failure else "degraded"
    refs = [
        f"t2-recovery:{record.get('receipt_id')}"
        for record in related
        if isinstance(record.get("receipt_id"), str)
    ]
    return {
        "status": "matched",
        "recovery_state": state,
        "attempt_count": len(related),
        "latest_route_ref": str(latest.get("route_ref") or "unknown"),
        "latest_failure_class": str(latest.get("failure_class") or "none"),
        "latest_observed_at": str(latest.get("observed_at") or "unknown"),
        "legacy_detail_unavailable": any(record.get("route_ref") == "legacy" for record in related),
        "evidence_refs": refs,
    }


def render_t2_recovery_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if evidence.get("tool") != "query_t2_recovery":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("status") == "none":
        return (
            "저장된 T2 proposer 실패 또는 복구 근거가 없습니다."
            if korean
            else "No retained T2 proposer failure or recovery evidence is available."
        )
    state = str(result.get("recovery_state") or "unknown")
    attempts = int(result.get("attempt_count") or 0)
    failure_class = str(result.get("latest_failure_class") or "unknown")
    route_ref = str(result.get("latest_route_ref") or "unknown")
    observed_at = str(result.get("latest_observed_at") or "unknown")
    legacy = result.get("legacy_detail_unavailable") is True
    if korean:
        lines = [
            f"T2 proposer 상태는 {state}이며 보존된 시도 {attempts}개를 확인했습니다.",
            f"최신 route 역할은 {route_ref}, failure class는 {failure_class}, "
            f"관찰 시각은 {observed_at}입니다.",
        ]
        if legacy:
            lines.append(
                "이 기록은 legacy audit에서 복구되어 원래 provider 오류 상세는 사용할 수 없습니다."
            )
        return " ".join(lines)
    lines = [
        f"The T2 proposer recovery state is {state} with {attempts} retained attempt(s).",
        f"The latest route role is {route_ref}, failure class is {failure_class}, "
        f"observed at {observed_at}.",
    ]
    if legacy:
        lines.append(
            "This record was recovered from legacy audit, so the original provider "
            "error detail is unavailable."
        )
    return " ".join(lines)


def t2_recovery_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return ()
    refs = result.get("evidence_refs")
    if not isinstance(refs, list):
        return ()
    return tuple(str(ref) for ref in refs if isinstance(ref, str))


__all__ = [
    "T2RecoveryChatTools",
    "T2RecoveryStateReader",
    "needs_t2_recovery_evidence",
    "render_t2_recovery_answer",
    "t2_recovery_evidence_refs",
]
