"""Capability catalog - what FDAI can do, projected to the console.

Slide 20 ("what you can do with the SRE Agent") maps onto a **capability
catalog**: a customer-agnostic registry of the control plane's capabilities
that the read-only console renders so an operator can discover what is
available, its safety class, and its default autonomy mode.

Every entry is inert metadata - listing a capability grants no execution
eligibility. The ``side_effect_class`` mirrors the console-tool taxonomy in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
(read / simulate / approve / execute / breakglass) and ``default_mode`` is
``shadow`` for any capability that can mutate, so the catalog can never
imply an ungated auto-action.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from fdai.shared.contracts.models import Mode


class CapabilityCategory(StrEnum):
    """Top-level grouping for a capability in the console."""

    DETECTION = "detection"
    INVESTIGATION = "investigation"
    REMEDIATION = "remediation"
    CHAOS = "chaos"
    KNOWLEDGE = "knowledge"
    INCIDENT = "incident"
    SCHEDULING = "scheduling"
    RESPONSE_PLAN = "response_plan"
    COST = "cost"
    REPORTING = "reporting"


class SideEffectClass(StrEnum):
    """The strongest side effect a capability can have (console taxonomy)."""

    READ = "read"
    SIMULATE = "simulate"
    APPROVE = "approve"
    EXECUTE = "execute"
    BREAKGLASS = "breakglass"


class CapabilityParity(StrEnum):
    """How FDAI realizes a comparable external SRE-agent capability."""

    NATIVE = "native"
    SAFER_ALTERNATIVE = "safer-alternative"
    EXTERNAL_BINDING = "external-binding"


@dataclass(frozen=True, slots=True)
class Capability:
    """One discoverable control-plane capability (inert metadata)."""

    capability_id: str
    name: str
    category: CapabilityCategory
    summary: str
    side_effect_class: SideEffectClass
    default_mode: Mode = Mode.SHADOW
    required_role: str = "reader"
    slide_ref: str | None = None
    enabled: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)
    parity: CapabilityParity = CapabilityParity.NATIVE
    official_source: str | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.capability_id:
            raise ValueError("Capability.capability_id MUST be non-empty")
        if self.official_source is not None and not self.official_source.startswith("https://"):
            raise ValueError("Capability.official_source MUST use HTTPS")
        if any(not ref.strip() or len(ref) > 300 for ref in self.evidence_refs):
            raise ValueError("Capability.evidence_refs MUST be non-empty and bounded")
        # A capability that can mutate MUST default to shadow - listing it can
        # never imply an ungated auto-action.
        if (
            self.side_effect_class in (SideEffectClass.EXECUTE, SideEffectClass.BREAKGLASS)
            and self.default_mode is not Mode.SHADOW
        ):
            raise ValueError(
                f"capability {self.capability_id} can mutate; default_mode MUST be shadow"
            )


class DuplicateCapabilityError(ValueError):
    """Raised when a capability_id is registered twice."""


class CapabilityCatalog:
    """An ordered, queryable registry of capabilities."""

    __slots__ = ("_by_id",)

    def __init__(self, capabilities: Sequence[Capability] = ()) -> None:
        self._by_id: dict[str, Capability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        if capability.capability_id in self._by_id:
            raise DuplicateCapabilityError(capability.capability_id)
        self._by_id[capability.capability_id] = capability

    def get(self, capability_id: str) -> Capability | None:
        return self._by_id.get(capability_id)

    def list(
        self,
        *,
        category: CapabilityCategory | None = None,
        enabled_only: bool = True,
    ) -> tuple[Capability, ...]:
        """Return capabilities, optionally filtered by category / enabled."""
        items = [
            cap
            for cap in self._by_id.values()
            if (category is None or cap.category is category) and (not enabled_only or cap.enabled)
        ]
        items.sort(key=lambda c: (c.category.value, c.name))
        return tuple(items)

    def as_console_view(self) -> tuple[dict[str, object], ...]:
        """Serialize the enabled catalog for the read-only console."""
        return tuple(
            {
                "capability_id": cap.capability_id,
                "name": cap.name,
                "category": cap.category.value,
                "summary": cap.summary,
                "side_effect_class": cap.side_effect_class.value,
                "default_mode": cap.default_mode.value,
                "required_role": cap.required_role,
                "slide_ref": cap.slide_ref,
                "tags": list(cap.tags),
                "parity": cap.parity.value,
                "official_source": cap.official_source,
                "evidence_refs": list(cap.evidence_refs),
            }
            for cap in self.list()
        )


__all__ = [
    "Capability",
    "CapabilityCatalog",
    "CapabilityCategory",
    "CapabilityParity",
    "DuplicateCapabilityError",
    "SideEffectClass",
]
