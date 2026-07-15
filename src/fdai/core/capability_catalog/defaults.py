"""The default FDAI capability catalog (customer-agnostic).

Enumerates the control-plane capabilities the console surfaces, including
the ones added for the SRE-agent parity slides (8-20). Entries are inert
metadata; ``side_effect_class`` and ``default_mode`` describe safety, they
do not grant it.
"""

from __future__ import annotations

from fdai.core.capability_catalog.catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.shared.contracts.models import Mode

_CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        capability_id="knowledge.register",
        name="Register knowledge + code sources",
        category=CapabilityCategory.KNOWLEDGE,
        summary="Connect knowledge documents and code repositories to ground analysis.",
        side_effect_class=SideEffectClass.EXECUTE,
        default_mode=Mode.SHADOW,
        required_role="contributor",
        slide_ref="8",
        tags=("rag", "code-access"),
    ),
    Capability(
        capability_id="chaos.run_experiment",
        name="Run a fault-injection experiment",
        category=CapabilityCategory.CHAOS,
        summary="Validate detect->mitigate with a governed, reversible fault injection.",
        side_effect_class=SideEffectClass.EXECUTE,
        default_mode=Mode.SHADOW,
        required_role="approver",
        slide_ref="9",
        tags=("resilience", "hil"),
    ),
    Capability(
        capability_id="investigation.run",
        name="Investigate across resources",
        category=CapabilityCategory.INVESTIGATION,
        summary="On-demand cross-resource investigation producing RCA + P1..P3 recommendations.",
        side_effect_class=SideEffectClass.READ,
        default_mode=Mode.SHADOW,
        required_role="reader",
        slide_ref="10-14",
        tags=("rca", "timeline"),
    ),
    Capability(
        capability_id="investigation.report",
        name="Investigation report",
        category=CapabilityCategory.REPORTING,
        summary="Timeline + correlation + prioritized recommendations within a latency budget.",
        side_effect_class=SideEffectClass.READ,
        required_role="reader",
        slide_ref="13-14",
        tags=("report",),
    ),
    Capability(
        capability_id="incident.create",
        name="Create an incident",
        category=CapabilityCategory.INCIDENT,
        summary=(
            "Prepare and confirm an incident with severity and correlation; "
            "audit it and notify subscribers."
        ),
        side_effect_class=SideEffectClass.EXECUTE,
        default_mode=Mode.SHADOW,
        required_role="contributor",
        slide_ref="15",
        tags=("gitops", "handoff"),
    ),
    Capability(
        capability_id="scheduler.create_task",
        name="Create a scheduled monitoring task",
        category=CapabilityCategory.SCHEDULING,
        summary="Create a recurring monitoring job that re-enters the control loop.",
        side_effect_class=SideEffectClass.EXECUTE,
        default_mode=Mode.SHADOW,
        required_role="contributor",
        slide_ref="16",
        tags=("scheduler",),
    ),
    Capability(
        capability_id="irp.author",
        name="Author an incident response plan",
        category=CapabilityCategory.RESPONSE_PLAN,
        summary="Author a gated response plan and pretest it against similar incidents.",
        side_effect_class=SideEffectClass.SIMULATE,
        required_role="contributor",
        slide_ref="17",
        tags=("irp", "pretest"),
    ),
    Capability(
        capability_id="irp.respond",
        name="Respond to an alert (IRP)",
        category=CapabilityCategory.RESPONSE_PLAN,
        summary="Alert -> budgeted investigation -> proposed mitigation -> HIL -> notify.",
        side_effect_class=SideEffectClass.APPROVE,
        required_role="approver",
        slide_ref="18",
        tags=("irp", "hil", "chatops"),
    ),
    Capability(
        capability_id="cost.metering",
        name="Usage + cost metering",
        category=CapabilityCategory.COST,
        summary="Token-to-cost rollups per conversation, day, and month.",
        side_effect_class=SideEffectClass.READ,
        required_role="reader",
        slide_ref="21",
        tags=("finops", "aau"),
    ),
)


def default_capability_catalog() -> CapabilityCatalog:
    """Return the customer-agnostic default capability catalog."""
    return CapabilityCatalog(_CAPABILITIES)


__all__ = ["default_capability_catalog"]
