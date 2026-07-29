"""Bounded resource selection context for verified chat follow-ups."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

_RESOURCE_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$")
_RESOURCE_TYPE: Final = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,127}$")
_HISTORY_FOLLOWUP: Final = re.compile(
    r"\b(?:since when|when did|when was|how long|history)\b|"
    r"언제부터|언제.{0,20}(?:중지|정지|변경)|얼마나 오래|이력",
    re.IGNORECASE,
)
_ATTRIBUTION_FOLLOWUP: Final = re.compile(r"\bwho\b|누가|변경 주체", re.IGNORECASE)


def parse_resource_context(raw: object) -> dict[str, str] | None:
    """Parse one client-returned selector hint without granting it authority."""

    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("resource_context MUST be an object")
    name = raw.get("name")
    resource_type = raw.get("resource_type")
    evidence_ref = raw.get("evidence_ref")
    if not isinstance(name, str) or _RESOURCE_NAME.fullmatch(name) is None:
        raise ValueError("resource_context.name MUST be a bounded resource name")
    if not isinstance(resource_type, str) or _RESOURCE_TYPE.fullmatch(resource_type) is None:
        raise ValueError("resource_context.resource_type MUST be a bounded resource type")
    if (
        not isinstance(evidence_ref, str)
        or not evidence_ref.startswith("inventory:")
        or len(evidence_ref) > 1024
    ):
        raise ValueError("resource_context.evidence_ref MUST be an inventory reference")
    return {
        "name": name,
        "resource_type": resource_type,
        "evidence_ref": evidence_ref,
    }


def contextualize_resource_followup(
    prompt: str,
    resource_context: Mapping[str, str] | None,
) -> tuple[str, bool]:
    """Bind an elliptical history question to the prior verified resource selector."""

    if resource_context is None or not (
        _HISTORY_FOLLOWUP.search(prompt) or _ATTRIBUTION_FOLLOWUP.search(prompt)
    ):
        return prompt, False
    name = resource_context["name"]
    if _ATTRIBUTION_FOLLOWUP.search(prompt):
        return f"누가 {name}을 중지하거나 변경했어? {prompt}", True
    return f"{name} 변경 이력: {prompt}", True


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
    return dict(fallback) if fallback is not None else None


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


__all__ = [
    "contextualize_resource_followup",
    "parse_resource_context",
    "resource_followup_answer",
    "response_resource_context",
]
