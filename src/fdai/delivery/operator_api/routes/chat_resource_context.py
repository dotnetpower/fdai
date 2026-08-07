"""Bounded resource selection context for verified chat follow-ups."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.delivery.operator_api.application.conversation.request_preparation import (
    parse_resource_context,
)
from fdai.delivery.operator_api.application.conversation.verification import AnswerVerification


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
    "resource_followup_answer",
    "resource_followup_verification",
    "response_resource_context",
]
