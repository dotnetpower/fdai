"""Deterministic English and Korean read-investigation intent routing."""

from __future__ import annotations

import re

from fdai.shared.providers.read_investigation import ReadInvestigationIntent

_GUEST = re.compile(
    r"(?:guest|os|operating system|event log|syslog|inside the vm|"
    r"게스트|운영체제|운영 체제|이벤트 로그|시스템 로그|가상 머신 내부).{0,32}"
    r"(?:shutdown|shut down|power off|stop|종료|정지|중지)|"
    r"(?:shutdown|shut down|종료).{0,32}(?:event log|syslog|게스트|운영체제|운영 체제)",
    re.IGNORECASE,
)
_ATTRIBUTION = re.compile(
    r"\bwho\b.{0,48}\b(?:stop|stopped|deallocate|deallocated|change|changed|restart|delete)d?\b|"
    r"\b(?:actor|caller|initiator|principal)\b|"
    r"누가.{0,48}(?:중지|정지|종료|할당 해제|변경|재시작|삭제)|"
    r"(?:행위자|호출자|작업자|변경 주체)",
    re.IGNORECASE,
)
_HISTORY = re.compile(
    r"\b(?:activity log|change history|resource history|recent changes?|operation history)\b|"
    r"(?:활동 로그|변경 이력|리소스 이력|최근 변경|작업 이력)",
    re.IGNORECASE,
)
_HEALTH = re.compile(
    r"\b(?:resource health|platform health|platform outage|host failure|maintenance event)\b|"
    r"(?:리소스 상태|플랫폼 상태|플랫폼 장애|호스트 장애|유지 관리)",
    re.IGNORECASE,
)
_STATE = re.compile(
    r"\b(?:current state|resource state|vm state|power state|status|running|stopped|deallocated)\b|"
    r"(?:현재 상태|리소스 상태|가상 머신 상태|전원 상태|실행 중|중지됨|할당 해제)",
    re.IGNORECASE,
)
_RESOURCE_TOKEN = re.compile(r"(?<![A-Za-z0-9_.()-])[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}")
_RESOURCE_WORDS = frozenset(
    {
        "activity",
        "current",
        "event",
        "guest",
        "health",
        "history",
        "platform",
        "resource",
        "shutdown",
        "state",
        "stopped",
    }
)


def classify_read_investigation_intent(question: str) -> ReadInvestigationIntent | None:
    """Classify only explicit read questions; ambiguous prose abstains."""
    normalized = " ".join(question.split())
    if not normalized:
        return None
    if _ATTRIBUTION.search(normalized):
        return ReadInvestigationIntent.CHANGE_ATTRIBUTION
    if _GUEST.search(normalized):
        return ReadInvestigationIntent.GUEST_SHUTDOWN
    if _HISTORY.search(normalized):
        return ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY
    if _HEALTH.search(normalized):
        return ReadInvestigationIntent.PLATFORM_HEALTH
    if _STATE.search(normalized):
        return ReadInvestigationIntent.RESOURCE_STATE
    return None


def resource_name_from_question(question: str) -> str | None:
    """Return one identifier-like resource name or abstain on ambiguity."""
    candidates = [
        token
        for token in _RESOURCE_TOKEN.findall(question)
        if token.casefold() not in _RESOURCE_WORDS
        and ("-" in token or any(character.isdigit() for character in token))
    ]
    unique = tuple(dict.fromkeys(candidates))
    return unique[0] if len(unique) == 1 else None


__all__ = ["classify_read_investigation_intent", "resource_name_from_question"]
