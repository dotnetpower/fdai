"""Deterministic chat intent parsing for the built-in incident workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fdai.shared.contracts.models import IncidentSeverity

IncidentChatStatus = Literal["not_incident", "needs_details", "awaiting_confirmation"]

_INCIDENT_TERMS = ("incident", "case", "인시던트", "케이스", "장애")
_CREATE_TERMS = (
    "create",
    "open",
    "register",
    "start",
    "생성",
    "열어",
    "오픈",
    "등록",
    "접수",
)
_SEVERITY_TERMS: tuple[tuple[re.Pattern[str], IncidentSeverity], ...] = (
    (re.compile(r"\bsev[ -]?1\b|\bcritical\b|긴급"), IncidentSeverity.SEV1),
    (re.compile(r"\bsev[ -]?2\b|\bhigh\b|심각"), IncidentSeverity.SEV2),
    (re.compile(r"\bsev[ -]?3\b|\bmedium\b|보통"), IncidentSeverity.SEV3),
    (re.compile(r"\bsev[ -]?4\b|\blow\b|낮음"), IncidentSeverity.SEV4),
    (re.compile(r"\bsev[ -]?5\b|\binfo\b|정보"), IncidentSeverity.SEV5),
)
_EXPLICIT_TARGET = re.compile(
    r"(?:resource|target|correlation(?:_key)?|대상|리소스)\s*[:=]?\s*"
    r"([a-z0-9][a-z0-9._:/-]{1,199})",
    re.IGNORECASE,
)
_RESOURCE_TOKEN = re.compile(r"\b[a-z0-9][a-z0-9._:/-]{2,199}\b", re.IGNORECASE)
_DEFAULT_CONFIRMATION_TTL = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class IncidentCreationProposal:
    """Immutable proposal that must be confirmed by the requesting operator."""

    requested_by: str
    correlation_keys: tuple[str, ...]
    severity: IncidentSeverity
    source_text: str
    requested_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IncidentChatTurn:
    """One deterministic interpretation of an operator chat message."""

    status: IncidentChatStatus
    response: str
    proposal: IncidentCreationProposal | None = None


def prepare_incident_chat(
    text: str,
    *,
    requested_by: str,
    now: datetime | None = None,
    confirmation_ttl: timedelta = _DEFAULT_CONFIRMATION_TTL,
) -> IncidentChatTurn:
    """Interpret an incident-open request without creating a record."""
    normalized = text.strip().lower()
    korean = bool(re.search(r"[가-힣]", text))
    if not any(term in normalized for term in _INCIDENT_TERMS) or not any(
        term in normalized for term in _CREATE_TERMS
    ):
        response = (
            "Incident 생성 요청으로 확인되지 않았어. 케이스 생성 또는 장애 접수라고 말해줘."
            if korean
            else (
                "I did not identify an incident creation request. "
                "Ask to create an incident or open a case."
            )
        )
        return IncidentChatTurn(status="not_incident", response=response)

    severity = _severity_of(normalized)
    correlation_keys = _correlation_keys_of(normalized)
    missing: list[str] = []
    if severity is None:
        missing.append("severity")
    if not correlation_keys:
        missing.append("target")
    if missing:
        fields = ", ".join(missing)
        response = (
            f"Incident 생성 전에 {fields} 정보가 필요해. 예: SEV2, 대상 prod-api-01."
            if korean
            else f"I need {fields} before creating the incident. Example: SEV2, target prod-api-01."
        )
        return IncidentChatTurn(status="needs_details", response=response)

    resolved_severity = cast(IncidentSeverity, severity)
    requested_at = now or datetime.now(tz=UTC)
    proposal = IncidentCreationProposal(
        requested_by=requested_by,
        correlation_keys=correlation_keys,
        severity=resolved_severity,
        source_text=text,
        requested_at=requested_at,
        expires_at=requested_at + confirmation_ttl,
    )
    targets = ", ".join(correlation_keys)
    response = (
        f"{resolved_severity.value.upper()} Incident를 {targets} 대상으로 생성할게. "
        "확인하면 생성하고 알림을 시작해."
        if korean
        else (
            f"I will create a {resolved_severity.value.upper()} incident for {targets}. "
            "Confirm to create it and start notifications."
        )
    )
    return IncidentChatTurn(
        status="awaiting_confirmation",
        response=response,
        proposal=proposal,
    )


def _severity_of(text: str) -> IncidentSeverity | None:
    for pattern, severity in _SEVERITY_TERMS:
        if pattern.search(text):
            return severity
    return None


def _correlation_keys_of(text: str) -> tuple[str, ...]:
    explicit = tuple(
        dict.fromkeys(f"resource:{match.group(1)}" for match in _EXPLICIT_TARGET.finditer(text))
    )
    if explicit:
        return explicit

    candidates: list[str] = []
    for token in _RESOURCE_TOKEN.findall(text):
        if token.startswith("sev") or token in _INCIDENT_TERMS or token in _CREATE_TERMS:
            continue
        if "-" in token or any(character.isdigit() for character in token):
            candidates.append(f"resource:{token}")
    return tuple(dict.fromkeys(candidates[:4]))


__all__ = [
    "IncidentChatStatus",
    "IncidentChatTurn",
    "IncidentCreationProposal",
    "prepare_incident_chat",
]