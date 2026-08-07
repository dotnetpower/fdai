"""Deterministic active network reachability evidence for Command Deck."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from fdai.delivery.operator_api.application.conversation.capabilities.system_health import (
    ChatToolResolver,
)

_APPLICATION: Final = re.compile(r"\b(?:application|app)\b|애플리케이션|앱", re.IGNORECASE)
_DATABASE: Final = re.compile(r"\b(?:database|db)\b|데이터베이스", re.IGNORECASE)
_REACHABILITY: Final = re.compile(
    r"\b(?:reach|reachable|connectivity|communicate|end[- ]to[- ]end)\b|"
    r"통신|연결|도달",
    re.IGNORECASE,
)
_MUTATION: Final = re.compile(
    r"\b(?:allow|open|configure|create|delete|fix|remediate)\b|"
    r"허용해|열어|설정해|생성|삭제|수정|복구",
    re.IGNORECASE,
)


class NetworkReachabilityProvider(Protocol):
    """Run one composition-owned active reachability probe."""

    async def query_reachability(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class NetworkReachabilityChatTools:
    provider: NetworkReachabilityProvider | None = None
    fallback: ChatToolResolver | None = None

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_network_reachability(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        if self.provider is None:
            result: Mapping[str, Any] = {
                "status": "unavailable",
                "reason": "active_probe_not_configured",
            }
        else:
            try:
                result = await self.provider.query_reachability()
            except Exception as exc:  # noqa: BLE001 - provider boundary fails closed
                result = {
                    "status": "unavailable",
                    "reason": type(exc).__name__,
                }
        return {
            "tool": "query_network_reachability",
            "authority": "server_network_probe",
            "result": dict(result),
        }


def needs_network_reachability(prompt: str) -> bool:
    return bool(
        _APPLICATION.search(prompt)
        and _DATABASE.search(prompt)
        and _REACHABILITY.search(prompt)
        and not _MUTATION.search(prompt)
    )


def render_network_reachability_answer(
    evidence: Mapping[str, Any],
    *,
    locale: str | None,
) -> str | None:
    if evidence.get("tool") != "query_network_reachability":
        return None
    result = evidence.get("result")
    if not isinstance(result, Mapping):
        return None
    korean = bool(locale and locale.casefold().startswith("ko"))
    if result.get("status") != "matched":
        return (
            "서버에 등록된 end-to-end active probe가 없어 애플리케이션과 데이터베이스 사이의 "
            "실제 통신 가능 여부를 확인하지 않았습니다. NSG 또는 peering 구성만으로는 "
            "도달 가능성을 증명할 수 없습니다."
            if korean
            else (
                "No server-registered end-to-end active probe is available, so actual "
                "application-to-database reachability was not confirmed. NSG or peering "
                "configuration alone does not prove reachability."
            )
        )
    reachable = result.get("reachable")
    observed_at = result.get("observed_at")
    http_status = result.get("http_status")
    if not isinstance(reachable, bool) or not isinstance(observed_at, str):
        return None
    if korean:
        conclusion = "통신할 수 있습니다" if reachable else "통신할 수 없습니다"
        return (
            f"등록된 end-to-end active probe 기준으로 애플리케이션에서 데이터베이스 경로까지 "
            f"{conclusion}. 관찰 시각: {observed_at}. HTTP 상태: {http_status}."
        )
    conclusion = "reachable" if reachable else "not reachable"
    return (
        "The registered end-to-end active probe found the application-to-database path "
        f"{conclusion}. Observed: {observed_at}. HTTP status: {http_status}."
    )


def network_reachability_evidence_refs(evidence: Mapping[str, Any]) -> tuple[str, ...]:
    result = evidence.get("result")
    if not isinstance(result, Mapping) or result.get("status") != "matched":
        return ()
    observed_at = result.get("observed_at")
    probe_alias = result.get("probe_alias")
    if not isinstance(observed_at, str) or not isinstance(probe_alias, str):
        return ()
    return (f"network-reachability:{probe_alias}@{observed_at}",)


__all__ = [
    "NetworkReachabilityChatTools",
    "NetworkReachabilityProvider",
    "needs_network_reachability",
    "network_reachability_evidence_refs",
    "render_network_reachability_answer",
]
