"""Compact descriptor selection shared by semantic planning entry points."""

from __future__ import annotations

from .conversation_preflight import (
    ContextDependency,
    ConversationPreflightResult,
    OperationalPreflightFamily,
    OperationalSignal,
)

DIRECT_RESPONSE_PROFILE = {
    "schema_version": "1.0.0",
    "identity": "Bragi",
    "product": "FDAI Console",
    "role": "read-only conversation interface",
    "voice": ("calm", "precise", "respectful", "evidence-first"),
    "interaction_style": (
        "acknowledge conversation continuity",
        "offer a concise operationally relevant next step",
        "avoid repeating a full self-introduction",
    ),
    "capabilities": (
        "explain current-screen and operational information from verified evidence",
        "prepare bounded requests for FDAI governed paths",
    ),
    "authority_boundaries": (
        "does not execute managed-resource changes",
        "does not approve its own requests",
        "does not claim verification without evidence",
    ),
}

PREFLIGHT_DIRECT_CONFIDENCE = 0.9
_PREFLIGHT_OPERATIONAL_INTENTS = {
    OperationalPreflightFamily.INVENTORY_DOCUMENT: "create.document",
    OperationalPreflightFamily.RESOURCE_CONFIGURATION_CHANGES: (
        "query.resource_configuration_changes"
    ),
    OperationalPreflightFamily.GATEWAY_DIAGNOSTIC_EVIDENCE: ("query.gateway_diagnostic_evidence"),
    OperationalPreflightFamily.RESOURCE_CURRENT_STATE: "query.resource_current_state",
    OperationalPreflightFamily.RECENT_RESOURCE_CHANGES: "query.resource_change_activity",
    OperationalPreflightFamily.RECENT_RESOURCE_STATE_CHANGES: "query.resource_change_activity",
    OperationalPreflightFamily.SUBSCRIPTION_SCOPE_IDENTITY: "query.subscription_scope_identity",
    OperationalPreflightFamily.SUBSCRIPTION_SERVICE_HEALTH: "query.subscription_service_health",
}


def preflight_descriptor_intent(result: ConversationPreflightResult | None) -> str | None:
    """Select a compact descriptor family without granting preflight authority."""

    if result is None or not result.attempted or result.failure_kind is not None:
        return None
    proposal = result.proposal
    if proposal is None or (
        proposal.confidence < PREFLIGHT_DIRECT_CONFIDENCE
        or proposal.operational_signal is not OperationalSignal.EXPLICIT
        or proposal.context_dependency is not ContextDependency.NONE
    ):
        return None
    if proposal.operational_family is OperationalPreflightFamily.RESOURCE_COLLECTION:
        return (
            "query.resource_state_inventory"
            if any(
                target.kind == "resource_state_filter" for target in proposal.operational_targets
            )
            else "query.contextual_resources"
        )
    return _PREFLIGHT_OPERATIONAL_INTENTS.get(proposal.operational_family)


__all__ = [
    "DIRECT_RESPONSE_PROFILE",
    "PREFLIGHT_DIRECT_CONFIDENCE",
    "preflight_descriptor_intent",
]
