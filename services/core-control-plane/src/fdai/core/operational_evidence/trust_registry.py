"""Pinned trust registry and deployment anchor bindings for operational evidence.

The upstream registry holds logical identifiers only. Deployment configuration binds each
logical anchor to a workload principal; neither the binding nor the proof-store address ever
enters the repository. A top-level defect makes every purpose unavailable, while a defect in one
purpose entry makes only that purpose unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.decision_evidence import LiveEvidenceClaimRequirement
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.venue import ExecutionVenue

from .registry_json import (
    RegistryUnavailableError,
    RevisionClass,
    ValidityWindow,
)

TRUST_REGISTRY_ID = "fdai.operational-evidence.trust-registry"


Venue = ExecutionVenue
"""The repository's authoritative execution venue; loopback anchors are local-only."""


class AnchorEvidenceClass(StrEnum):
    """Evidence class of one bound principal."""

    LIVE = "live"
    LOCAL_LOOPBACK = "local-loopback"


@dataclass(frozen=True, slots=True)
class ProducerEntry:
    """A registered requesting boundary; claiming it grants nothing without its anchor."""

    producer_id: str
    producer_version: str
    anchor_id: str


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """One authoritative or corroborating source and the anchor of its only writer."""

    source_id: str
    role: str
    anchor_id: str


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    """Registry-owned freshness ceiling; its digest is the freshness proof subject."""

    policy_id: str
    policy_version: str
    ceiling_seconds: int

    @property
    def digest(self) -> str:
        """Return the canonical freshness policy digest used by receipts and requirements."""

        return content_digest(
            {
                "freshness_ceiling_seconds": self.ceiling_seconds,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
            }
        )


@dataclass(frozen=True, slots=True)
class VerifierEntry:
    """One reviewed verifier version; rotation adds an entry beside the one it replaces."""

    verifier_id: str
    verifier_version: str
    trust_anchor_id: str
    window: ValidityWindow

    @property
    def key(self) -> tuple[str, str, str]:
        """Return the identity that must survive a routine rotation unchanged."""

        return (self.verifier_id, self.verifier_version, self.trust_anchor_id)


@dataclass(frozen=True, slots=True)
class PurposeTrust:
    """The reviewed evidence contract of exactly one purpose."""

    purpose_id: str
    authority_class: str
    method_id: str
    method_version: str
    evidence_class: str
    producers: tuple[ProducerEntry, ...]
    sources: tuple[SourceEntry, ...]
    freshness: FreshnessPolicy
    verifiers: tuple[VerifierEntry, ...]
    separation: tuple[str, ...]
    revoked: bool

    def producer(self, producer_id: str, producer_version: str) -> ProducerEntry | None:
        """Return the exact registered producer or nothing."""

        return next(
            (
                item
                for item in self.producers
                if (item.producer_id, item.producer_version) == (producer_id, producer_version)
            ),
            None,
        )

    def active_verifier(self, verifier_id: str, at: datetime) -> VerifierEntry | None:
        """Return the newest active binding for this verifier identity at one instant."""

        active = [
            item
            for item in self.verifiers
            if item.verifier_id == verifier_id and item.window.active_at(at)
        ]
        return max(active, key=lambda item: item.window.valid_from) if active else None

    def binding(self, key: tuple[str, str, str]) -> VerifierEntry | None:
        """Return the one binding with this exact verifier id, version, and trust anchor.

        Routine rotation adds a binding beside the one it replaces, so a record is always
        rechecked against the exact binding that issued it, never against the newest one.
        """

        return next((item for item in self.verifiers if item.key == key), None)

    def version_binding(self, verifier_id: str, verifier_version: str) -> VerifierEntry | None:
        """Return the single binding for one deployed verifier version, or nothing."""

        matches = [
            item
            for item in self.verifiers
            if (item.verifier_id, item.verifier_version) == (verifier_id, verifier_version)
        ]
        return matches[0] if len(matches) == 1 else None

    def authoritative_source_ids(self) -> tuple[str, ...]:
        """Return the ordered sources whose identity may appear on an issued receipt."""

        return tuple(
            sorted(item.source_id for item in self.sources if item.role == "authoritative")
        )

    def requirement(
        self,
        *,
        scope_digest: str,
        producer: ProducerEntry,
        source_revision: str,
    ) -> LiveEvidenceClaimRequirement:
        """Return the gate requirement derived from this entry, never from the request."""

        return LiveEvidenceClaimRequirement(
            allowed_authority_classes=(self.authority_class,),
            allowed_source_identities=self.authoritative_source_ids(),
            scope_digest=scope_digest,
            purpose_id=self.purpose_id,
            producer_id=producer.producer_id,
            producer_version=producer.producer_version,
            method_id=self.method_id,
            method_version=self.method_version,
            source_revision=source_revision,
            freshness_policy_digest=self.freshness.digest,
            freshness_ceiling_seconds=self.freshness.ceiling_seconds,
        )

    def anchor_ids(self) -> frozenset[str]:
        """Return every anchor this entry requires a deployment binding for."""

        return self.independent_anchor_ids() | {item.trust_anchor_id for item in self.verifiers}

    def independent_anchor_ids(self) -> frozenset[str]:
        """Return the producer, source, and separation anchors the verifier must differ from.

        Separation checks skip only anchors that verifier bindings use exclusively, so an
        anchor that is also a producer, source, or separation anchor always stays here.
        """

        return frozenset(
            {
                *(item.anchor_id for item in self.producers),
                *(item.anchor_id for item in self.sources),
                *self.separation,
            }
        )

    def shared_verifier_anchors(self) -> frozenset[str]:
        """Return verifier trust anchors that are also independent anchors; any one is a defect."""

        return (
            frozenset(item.trust_anchor_id for item in self.verifiers)
            & self.independent_anchor_ids()
        )


@dataclass(frozen=True, slots=True)
class TrustRegistry:
    """One pinned registry revision with valid purposes and per-purpose defects."""

    pin: str
    revision: int
    purposes: Mapping[str, PurposeTrust]
    defects: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def purpose(self, purpose_id: str) -> PurposeTrust | None:
        """Return a valid, unrevoked entry or nothing."""

        entry = self.purposes.get(purpose_id)
        return entry if entry is not None and not entry.revoked else None


@dataclass(frozen=True, slots=True)
class AnchorBinding:
    """Deployment-owned binding of one logical anchor to one principal."""

    anchor_id: str
    principal_id: str
    evidence_class: AnchorEvidenceClass


@dataclass(frozen=True, slots=True)
class DeploymentAnchors:
    """Anchor bindings from deployment configuration, bound to the resolved execution venue."""

    venue: Venue
    bindings: Mapping[str, AnchorBinding]

    def principal(self, anchor_id: str) -> str | None:
        """Return the bound principal for one anchor or nothing."""

        binding = self.bindings.get(anchor_id)
        return binding.principal_id if binding is not None else None


def purpose_defects(
    registry: TrustRegistry,
    anchors: DeploymentAnchors,
    *,
    purpose_id: str,
    verifier_id: str,
    at: datetime,
    verifier_version: str | None = None,
) -> tuple[str, ...]:
    """Return why one purpose cannot issue; an empty tuple means registry-level readiness.

    With ``verifier_version`` the workload's own binding must be active; without it, any
    active binding of the verifier identity suffices, as a consumer rechecking old records needs.
    """

    if purpose_id in registry.defects:
        return registry.defects[purpose_id]
    entry = registry.purposes.get(purpose_id)
    if entry is None:
        return ("purpose_not_registered",)
    if entry.revoked:
        return ("purpose_revoked",)
    verifier = (
        entry.active_verifier(verifier_id, at)
        if verifier_version is None
        else entry.version_binding(verifier_id, verifier_version)
    )
    if verifier is None or not verifier.window.active_at(at):
        return ("verifier_binding_inactive",)
    missing = sorted(anchor for anchor in entry.anchor_ids() if anchor not in anchors.bindings)
    if missing:
        return ("anchor_missing",)
    reasons: list[str] = []
    if anchors.venue is Venue.DEPLOYED and any(
        anchors.bindings[anchor].evidence_class is AnchorEvidenceClass.LOCAL_LOOPBACK
        for anchor in entry.anchor_ids()
    ):
        reasons.append("local_loopback_anchor_in_deployed_venue")
    verifier_principal = anchors.bindings[verifier.trust_anchor_id].principal_id
    if any(
        anchors.bindings[anchor].principal_id == verifier_principal
        for anchor in entry.independent_anchor_ids()
    ):
        reasons.append("self_verified")
    return tuple(sorted(reasons))


def classify_trust_revision(previous: TrustRegistry, current: TrustRegistry) -> RevisionClass:
    """Classify by content: any removal, narrowing, shortening, or revocation revokes."""

    for purpose_id, before in previous.purposes.items():
        after = current.purposes.get(purpose_id)
        if after is None or purpose_id in current.defects:
            return RevisionClass.REVOCATION
        if (after.revoked and not before.revoked) or _narrowed(before, after):
            return RevisionClass.REVOCATION
    return RevisionClass.ROUTINE_ROTATION


def _narrowed(before: PurposeTrust, after: PurposeTrust) -> bool:
    if (before.authority_class, before.method_id, before.method_version, before.evidence_class) != (
        after.authority_class,
        after.method_id,
        after.method_version,
        after.evidence_class,
    ):
        return True
    if not set(before.producers) <= set(after.producers):
        return True
    if not set(before.sources) <= set(after.sources) or not set(before.separation) <= set(
        after.separation
    ):
        return True
    if after.freshness.ceiling_seconds < before.freshness.ceiling_seconds:
        return True
    current = {item.key: item for item in after.verifiers}
    for verifier in before.verifiers:
        match = current.get(verifier.key)
        if match is None or verifier.window.narrowed_by(match.window):
            return True
    return False


__all__ = [
    "TRUST_REGISTRY_ID",
    "AnchorBinding",
    "AnchorEvidenceClass",
    "DeploymentAnchors",
    "FreshnessPolicy",
    "ProducerEntry",
    "PurposeTrust",
    "RegistryUnavailableError",
    "SourceEntry",
    "TrustRegistry",
    "Venue",
    "VerifierEntry",
    "classify_trust_revision",
    "purpose_defects",
]
