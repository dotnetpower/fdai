"""Operational-planning availability without granting execution authority."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.contracts.models import Mode


@dataclass(frozen=True, slots=True)
class OperationalPlanningCapabilityStatus:
    available: bool
    enabled: bool
    mode: Mode
    missing_requirements: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    @property
    def can_plan(self) -> bool:
        return self.available and self.enabled and self.mode is Mode.SHADOW

    def to_mapping(self) -> dict[str, object]:
        return {
            "available": self.available,
            "enabled": self.enabled,
            "mode": self.mode.value,
            "reason": self.unavailable_reason,
            "missing_requirements": list(self.missing_requirements),
        }


def operational_planning_capability_status(
    *,
    ontology_release_available: bool,
    operational_context_available: bool,
    process_store_available: bool,
    effect_model_reader_available: bool,
    causal_verifier_available: bool,
    enabled: bool = True,
) -> OperationalPlanningCapabilityStatus:
    requirements = (
        ("ontology_release", ontology_release_available),
        ("operational_context", operational_context_available),
        ("process_store", process_store_available),
        ("effect_model_reader", effect_model_reader_available),
        ("causal_evidence_verifier", causal_verifier_available),
    )
    missing = tuple(name for name, available in requirements if not available)
    reason = None
    if not enabled:
        reason = "pantheon runtime disabled"
    elif missing:
        reason = "missing planning prerequisites"
    return OperationalPlanningCapabilityStatus(
        available=not missing,
        enabled=enabled,
        mode=Mode.SHADOW,
        missing_requirements=missing,
        unavailable_reason=reason,
    )


__all__ = [
    "OperationalPlanningCapabilityStatus",
    "operational_planning_capability_status",
]
