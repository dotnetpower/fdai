"""Bounded resource selection context for verified chat follow-ups."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, TypeGuard

from fdai.core.read_investigation.routing import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.delivery.operator_api.application.conversation.verification import AnswerVerification
from fdai.shared.providers.read_investigation import ReadInvestigationIntent

_RESOURCE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$")
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


def is_bounded_resource_name(value: object) -> TypeGuard[str]:
    """Return whether a selector value is a bounded resource name."""

    return isinstance(value, str) and _RESOURCE_NAME.fullmatch(value) is not None


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


def response_resource_context(
    view_context: Mapping[str, Any],
    fallback: Mapping[str, str] | None = None,
) -> dict[str, str] | None:
    """Return one server-selected inventory resource or preserve a validated selector."""

    tool = view_context.get("_tool_evidence")
    if isinstance(tool, Mapping) and tool.get("tool") == "query_inventory":
        result = tool.get("result")
        if isinstance(result, Mapping) and result.get("status") == "matched":
            resources = result.get("resources")
            if isinstance(resources, list) and len(resources) == 1:
                resource = resources[0]
                source = result.get("source")
                snapshot = result.get("snapshot_at")
                if (
                    isinstance(resource, Mapping)
                    and isinstance(source, str)
                    and isinstance(snapshot, str)
                ):
                    try:
                        return parse_resource_context(
                            {
                                "name": resource.get("name"),
                                "resource_type": resource.get("type"),
                                "evidence_ref": f"inventory:{source}@{snapshot}",
                            }
                        )
                    except ValueError:
                        return None
    if isinstance(tool, Mapping) and tool.get("tool") == "query_subscription_health":
        query = tool.get("query")
        result = tool.get("result")
        if (
            isinstance(query, Mapping)
            and query.get("health_history") is True
            and isinstance(result, Mapping)
            and result.get("status") == "matched"
        ):
            events = result.get("health_history_events")
            source = result.get("source")
            observed_at = result.get("observed_at")
            if (
                isinstance(events, list)
                and events
                and isinstance(source, str)
                and isinstance(observed_at, str)
            ):
                latest = max(
                    (event for event in events if isinstance(event, Mapping)),
                    key=lambda event: str(event.get("observed_at") or ""),
                    default=None,
                )
                if latest is not None:
                    provider_type = str(latest.get("resource_type") or "azure-resource")
                    neutral_type = provider_type.casefold().replace("/", ".")
                    incident = max(
                        (
                            event
                            for event in events
                            if isinstance(event, Mapping)
                            and event.get("resource_name") == latest.get("resource_name")
                            and event.get("kind") == "availability_status"
                            and str(event.get("status") or "").casefold()
                            in {"degraded", "unavailable", "unknown"}
                        ),
                        key=lambda event: str(event.get("observed_at") or ""),
                        default=None,
                    )
                    candidate = {
                        "name": latest.get("resource_name"),
                        "resource_type": neutral_type,
                        "evidence_ref": f"subscription-health:{source}@{observed_at}",
                    }
                    if incident is not None and latest.get("resource_group"):
                        candidate.update(
                            {
                                "resource_group": latest.get("resource_group"),
                                "event_at": incident.get("observed_at"),
                                "event_status": incident.get("status"),
                            }
                        )
                    try:
                        return parse_resource_context(candidate)
                    except ValueError:
                        return None
    if fallback is not None and resource_followup_answer(view_context, fallback) is not None:
        return dict(fallback)
    return None


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def resource_followup_answer(
    view_context: Mapping[str, Any],
    resource_context: Mapping[str, str] | None,
) -> str | None:
    """Return Heimdall's answer only when its resolved resource matches the selector."""

    if resource_context is None:
        return None
    agent = view_context.get("_agent_evidence")
    if not isinstance(agent, Mapping) or agent.get("primary_agent") != "Heimdall":
        return None
    facts = agent.get("facts")
    answer = agent.get("answer")
    if (
        not isinstance(facts, Mapping)
        or facts.get("resource_name") != resource_context["name"]
        or not isinstance(answer, str)
        or not answer.strip()
        or len(answer) > 8_000
    ):
        return None
    return answer.strip()


def resource_followup_verification(
    view_context: Mapping[str, Any],
    resource_context: Mapping[str, str] | None,
) -> AnswerVerification | None:
    """Verify a matching Heimdall answer from bounded normalized read evidence."""

    answer = resource_followup_answer(view_context, resource_context)
    agent = view_context.get("_agent_evidence")
    if answer is None or not isinstance(agent, Mapping):
        return None
    facts = agent.get("facts")
    if not isinstance(facts, Mapping):
        return None
    if (
        facts.get("status") == "unavailable"
        and facts.get("intent") == "pre_incident_changes"
        and facts.get("reason") == "incident_anchor_unavailable"
    ):
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="server_read_investigation",
            checks_completed=0,
            checks_total=1,
            evidence_refs=(),
            reason_code="incident_anchor_unavailable",
        )
    if facts.get("status") == "queued":
        task_id = facts.get("task_id")
        message_id = facts.get("message_id")
        if (
            not isinstance(task_id, str)
            or not 1 <= len(task_id) <= 256
            or not isinstance(message_id, str)
            or not message_id.startswith("read-message:sha256:")
            or len(message_id) > 256
        ):
            return None
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="server_read_investigation",
            checks_completed=0,
            checks_total=1,
            evidence_refs=(),
            reason_code="background_task_queued",
        )
    if facts.get("status") == "handoff_required":
        if facts.get("mode") != "detached" or not isinstance(facts.get("estimated_upper_ms"), int):
            return None
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="server_read_investigation",
            checks_completed=0,
            checks_total=1,
            evidence_refs=(),
            reason_code="background_task_unavailable",
        )
    if (
        facts.get("status") in {"none", "unavailable"}
        and facts.get("intent") == "resource_state"
        and facts.get("read_availability_explanation") is True
    ):
        sources = facts.get("evidence_sources")
        if not isinstance(sources, (list, tuple)) or any(
            not isinstance(source, str) or not 1 <= len(source) <= 256 for source in sources
        ):
            return None
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="server_read_investigation",
            checks_completed=0,
            checks_total=max(1, len(sources)),
            evidence_refs=(),
            reason_code=(
                "read_state_not_observed"
                if facts.get("status") == "none"
                else "read_authority_unavailable"
            ),
        )
    if facts.get("status") in {"none", "unavailable", "ambiguous"}:
        return AnswerVerification(
            status="unverified",
            answer=answer,
            authority="server_read_investigation",
            checks_completed=0,
            checks_total=1,
            evidence_refs=(),
            reason_code=(
                "resource_history_ambiguous"
                if facts.get("status") == "ambiguous"
                else "resource_history_unavailable"
            ),
        )
    if facts.get("status") != "matched":
        return None
    raw_refs = facts.get("evidence_refs")
    if not isinstance(raw_refs, (list, tuple)) or not 1 <= len(raw_refs) <= 64:
        return None
    evidence_refs = tuple(raw_refs)
    if any(not isinstance(ref, str) or not ref or len(ref) > 1024 for ref in evidence_refs):
        return None
    return AnswerVerification(
        status="verified",
        answer=answer,
        authority="server_read_investigation",
        checks_completed=len(evidence_refs),
        checks_total=len(evidence_refs),
        evidence_refs=evidence_refs,
        reason_code=(
            "read_availability_grounded"
            if facts.get("read_availability_explanation") is True
            else "resource_history_grounded"
        ),
    )


__all__ = [
    "contextualize_resource_followup",
    "is_bounded_resource_name",
    "parse_resource_context",
    "resource_followup_answer",
    "resource_followup_verification",
    "response_resource_context",
]
