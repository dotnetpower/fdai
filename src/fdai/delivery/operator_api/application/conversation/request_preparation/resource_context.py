"""Bounded resource selection context for verified chat follow-ups."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from fdai.core.read_investigation.routing import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.delivery.operator_api.application.conversation.capabilities.inventory.contracts import (
    is_bounded_resource_name,
)
from fdai.shared.providers.read_investigation import ReadInvestigationIntent

_RESOURCE_TYPE: Final = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,127}$")
_RESOURCE_GROUP: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$")
_EVENT_STATUS: Final = re.compile(r"^[A-Za-z][A-Za-z0-9 _.-]{1,63}$")
_EVIDENCE_REF_PREFIXES: Final = ("inventory:", "subscription-health:")
_SELECTOR_REQUIRED_INTENTS: Final = frozenset(
    {
        ReadInvestigationIntent.CHANGE_ATTRIBUTION,
        ReadInvestigationIntent.RESOURCE_CHANGE_HISTORY,
        ReadInvestigationIntent.GUEST_SHUTDOWN,
    }
)
_HISTORY_FOLLOWUP: Final = re.compile(
    r"\b(?:since when|when did|when was|how long|history)\b|"
    r"언제부터|언제.{0,20}(?:중지|정지|변경)|얼마나 오래|이력",
    re.IGNORECASE,
)
_ATTRIBUTION_FOLLOWUP: Final = re.compile(
    r"\bwho\b|누가|(?:변경|작업|중지).{0,8}주체",
    re.IGNORECASE,
)
_LATEST_CHANGE_FOLLOWUP: Final = re.compile(
    r"\b(?:most recent|latest)\b.{0,32}\b(?:change|operation)\b|"
    r"\bwho\b.{0,32}\bchanged\b.{0,32}\bmost recently\b|"
    r"(?:가장 최근|최근).{0,24}(?:변경|작업)|누가.{0,32}(?:가장 최근|최근).{0,16}변경",
    re.IGNORECASE,
)
_PRE_INCIDENT_FOLLOWUP: Final = re.compile(
    r"(?:before|prior to|preceding).{0,48}(?:incident|outage)|"
    r"(?:incident|outage).{0,48}(?:before|prior|preceding)|"
    r"(?:장애|인시던트).{0,20}(?:직전|이전|전에|전의)|"
    r"(?:직전|이전|전에|전의).{0,20}(?:장애|인시던트)",
    re.IGNORECASE,
)
_READ_AVAILABILITY_FOLLOWUP: Final = re.compile(
    r"\bwhy\b.{0,48}(?:(?:cannot|can't|couldn't|unable).{0,32}(?:read|access)"
    r".{0,32}(?:state|status)|(?:health evidence).{0,24}unavailable)|"
    r"(?:리소스|자원).{0,24}상태.{0,24}"
    r"(?:읽을 수 없|조회할 수 없|조회가 불가능)|"
    r"(?:권한|범위|원본).{0,32}상태.{0,24}(?:읽지 못|읽을 수 없|조회하지 못|조회할 수 없)|"
    r"(?:이 리소스.{0,24})?(?:읽기 권한|권한|범위).{0,24}(?:제한|막힌|설명)",
    re.IGNORECASE,
)


def parse_resource_context(raw: object) -> dict[str, str] | None:
    """Parse one client-returned selector hint without granting it authority."""

    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("resource_context MUST be an object")
    name = raw.get("name")
    resource_type = raw.get("resource_type")
    evidence_ref = raw.get("evidence_ref")
    if not is_bounded_resource_name(name):
        raise ValueError("resource_context.name MUST be a bounded resource name")
    if not isinstance(resource_type, str) or _RESOURCE_TYPE.fullmatch(resource_type) is None:
        raise ValueError("resource_context.resource_type MUST be a bounded resource type")
    if (
        not isinstance(evidence_ref, str)
        or not evidence_ref.startswith(_EVIDENCE_REF_PREFIXES)
        or len(evidence_ref) > 1024
    ):
        raise ValueError("resource_context.evidence_ref MUST be an inventory reference")
    parsed = {
        "name": name,
        "resource_type": resource_type,
        "evidence_ref": evidence_ref,
    }
    resource_group = raw.get("resource_group")
    event_at = raw.get("event_at")
    event_status = raw.get("event_status")
    if any(value is not None for value in (resource_group, event_at, event_status)):
        if (
            not isinstance(resource_group, str)
            or _RESOURCE_GROUP.fullmatch(resource_group) is None
            or not isinstance(event_at, str)
            or not _valid_timestamp(event_at)
            or not isinstance(event_status, str)
            or _EVENT_STATUS.fullmatch(event_status) is None
        ):
            raise ValueError("resource_context incident anchor MUST be bounded and complete")
        parsed.update(
            {
                "resource_group": resource_group,
                "event_at": event_at,
                "event_status": event_status,
            }
        )
    return parsed


def contextualize_resource_followup(
    prompt: str,
    resource_context: Mapping[str, str] | None,
) -> tuple[str, bool]:
    """Bind an elliptical history question to the prior verified resource selector."""

    guest_shutdown = (
        classify_read_investigation_intent(prompt) is ReadInvestigationIntent.GUEST_SHUTDOWN
    )
    if resource_context is None or not (
        _HISTORY_FOLLOWUP.search(prompt)
        or _ATTRIBUTION_FOLLOWUP.search(prompt)
        or _PRE_INCIDENT_FOLLOWUP.search(prompt)
        or _READ_AVAILABILITY_FOLLOWUP.search(prompt)
        or guest_shutdown
    ):
        return prompt, False
    name = resource_context["name"]
    if _PRE_INCIDENT_FOLLOWUP.search(prompt) and all(
        field in resource_context for field in ("resource_group", "event_at", "event_status")
    ):
        locale = "ko" if re.search(r"[가-힣]", prompt) else "en"
        return (
            f"{name} change history: pre-incident activity "
            f"group={resource_context['resource_group']} "
            f"before={resource_context['event_at']} locale={locale}",
            True,
        )
    if _PRE_INCIDENT_FOLLOWUP.search(prompt):
        locale = "ko" if re.search(r"[가-힣]", prompt) else "en"
        return (
            f"{name} change history: pre-incident activity anchor=unavailable locale={locale}",
            True,
        )
    if _LATEST_CHANGE_FOLLOWUP.search(prompt):
        return f"{name} change history: show the most recent successful operation", True
    if _ATTRIBUTION_FOLLOWUP.search(prompt):
        return f"누가 {name}을 중지하거나 변경했어? {prompt}", True
    if _READ_AVAILABILITY_FOLLOWUP.search(prompt):
        locale = "ko" if re.search(r"[가-힣]", prompt) else "en"
        return f"{name} current state: explain read availability locale={locale}", True
    if guest_shutdown:
        return f"{name} guest shutdown: {prompt}", True
    return f"{name} 변경 이력: {prompt}", True


def missing_read_investigation_context_evidence(
    prompt: str,
    resource_context: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    """Return a typed hold when one read intent lacks its exact context."""

    if resource_context is not None:
        return None
    preincident = _PRE_INCIDENT_FOLLOWUP.search(prompt) is not None
    read_availability = _READ_AVAILABILITY_FOLLOWUP.search(prompt) is not None
    intent = classify_read_investigation_intent(prompt)
    if (
        not preincident
        and not read_availability
        and (
            intent not in _SELECTOR_REQUIRED_INTENTS
            or resource_name_from_question(prompt) is not None
        )
    ):
        return None
    required_context = "selected_incident" if preincident else "selected_resource"
    intent_name = (
        "pre_incident_investigation"
        if preincident
        else "read_availability"
        if read_availability
        else "resource_investigation"
    )
    return {
        "tool": "query_conversation_context",
        "authority": "server_conversation_context",
        "status": "abstain",
        "result": {
            "status": "unavailable",
            "reason": "prior_context_required",
            "intent": intent_name,
            "required_context": [required_context],
        },
    }


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


__all__ = [
    "contextualize_resource_followup",
    "missing_read_investigation_context_evidence",
    "parse_resource_context",
]
