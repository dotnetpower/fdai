"""Verify raw provider relationships against one complete inventory generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

from fdai.shared.providers.inventory import (
    LinkRecord,
    RelationshipDrop,
    RelationshipDropReason,
    ResourceRecord,
)
from fdai.shared.providers.state_evidence import (
    LinkObservationMetadata,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

DEFAULT_RELATIONSHIP_VERIFIER_IDENTITY = "fdai-inventory-generation-verifier"
DEFAULT_RELATIONSHIP_VERIFIER_REVISION = "inventory-generation-verifier.v1"


@dataclass(frozen=True, slots=True)
class VerifiedInventoryRelationships:
    """Verified active-link candidates and bounded suppression evidence."""

    links: tuple[LinkRecord, ...]
    dropped: tuple[RelationshipDrop, ...]


def verify_inventory_relationships(
    *,
    generation: str,
    resources: Sequence[ResourceRecord],
    links: Sequence[LinkRecord],
    complete: bool,
    recorded_at: datetime,
    upstream_drops: Sequence[RelationshipDrop] = (),
    verifier_identity: str | None = DEFAULT_RELATIONSHIP_VERIFIER_IDENTITY,
    verifier_revision: str = DEFAULT_RELATIONSHIP_VERIFIER_REVISION,
) -> VerifiedInventoryRelationships:
    """Verify links only when one complete generation observes both endpoints."""

    if not generation.strip():
        raise ValueError("relationship verification generation MUST be non-empty")
    if recorded_at.tzinfo is None:
        raise ValueError("relationship verification recorded_at MUST be timezone-aware")
    dropped = list(upstream_drops)
    if not complete:
        dropped.append(RelationshipDrop(reason=RelationshipDropReason.PARTIAL_GENERATION))
        return VerifiedInventoryRelationships(links=(), dropped=_canonical_drops(dropped))

    resources_by_id = _resources_by_id(resources)
    grouped: dict[tuple[str, str, str], list[LinkRecord]] = {}
    for link in links:
        grouped.setdefault((link.from_id, link.link_type, link.to_id), []).append(link)

    rejected_keys: set[tuple[str, str, str]] = set()
    for key, candidates in grouped.items():
        if len(candidates) == 1:
            continue
        reason = (
            RelationshipDropReason.DUPLICATE_EDGE
            if all(candidate == candidates[0] for candidate in candidates[1:])
            else RelationshipDropReason.CONFLICTING_DUPLICATE
        )
        dropped.append(_drop(reason, candidates[0]))
        rejected_keys.add(key)

    for key in grouped:
        link_type, from_id, to_id = key[1], key[0], key[2]
        reverse_key = (to_id, link_type, from_id)
        if link_type != "peered_with" and reverse_key in grouped:
            rejected_keys.update((key, reverse_key))
            dropped.append(_drop(RelationshipDropReason.CONFLICTING_DUPLICATE, grouped[key][0]))

    verified: list[LinkRecord] = []
    for key in sorted(grouped):
        if key in rejected_keys:
            continue
        link = grouped[key][0]
        evidence = link.mapping_evidence
        if evidence is None:
            dropped.append(_drop(RelationshipDropReason.UNVERIFIED_METADATA, link))
            continue
        if evidence.source_schema_digest != evidence.observed_schema_digest:
            dropped.append(_drop(RelationshipDropReason.STALE_SOURCE_SCHEMA_DIGEST, link))
            continue
        source = resources_by_id.get(link.from_id)
        target = resources_by_id.get(link.to_id)
        if source is None:
            dropped.append(_drop(RelationshipDropReason.MISSING_SOURCE_ENDPOINT, link))
            continue
        if target is None:
            dropped.append(_drop(RelationshipDropReason.MISSING_TARGET_ENDPOINT, link))
            continue
        if (source.type, target.type) != (link.from_type, link.to_type):
            dropped.append(_drop(RelationshipDropReason.CONFLICTING_DUPLICATE, link))
            continue
        if (
            verifier_identity is None
            or not verifier_identity.strip()
            or verifier_identity.casefold()
            in {evidence.provider_identity.casefold(), evidence.source_identity.casefold()}
        ):
            dropped.append(_drop(RelationshipDropReason.MISSING_INDEPENDENT_VERIFIER, link))
            continue
        owner = resources_by_id.get(evidence.provider_owner_id)
        effective_at = _observation_time(owner)
        if effective_at is None or effective_at > recorded_at:
            dropped.append(_drop(RelationshipDropReason.UNVERIFIED_METADATA, link))
            continue
        receipt_ref = _verification_receipt(
            generation=generation,
            link=link,
            verifier_identity=verifier_identity,
            verifier_revision=verifier_revision,
        )
        state_fact = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity=evidence.source_identity,
            source_revision=(f"{evidence.source_schema_version}:{evidence.source_schema_digest}"),
            effective_at=effective_at,
            recorded_at=recorded_at,
            evidence_cutoff=effective_at,
            freshness_ceiling_seconds=evidence.freshness_ceiling_seconds,
            completeness=1.0,
            synthetic=False,
            evidence_refs=(
                evidence.mapping_receipt_ref,
                evidence.observation_receipt_ref,
            ),
        )
        metadata = LinkObservationMetadata(
            state_fact=state_fact,
            verification_method=evidence.evidence_method,
            verified=True,
            verifier_identity=verifier_identity,
            verifier_revision=verifier_revision,
            verification_receipt_ref=receipt_ref,
            inventory_generation=generation,
            mapping_id=evidence.mapping_id,
            mapping_revision=evidence.mapping_revision,
            source_schema_version=evidence.source_schema_version,
            source_schema_digest=evidence.source_schema_digest,
        )
        verified.append(replace(link, observation_metadata=metadata))

    return VerifiedInventoryRelationships(
        links=tuple(verified),
        dropped=_canonical_drops(dropped),
    )


def _resources_by_id(resources: Sequence[ResourceRecord]) -> Mapping[str, ResourceRecord]:
    indexed: dict[str, ResourceRecord] = {}
    for resource in resources:
        prior = indexed.get(resource.resource_id)
        if prior is not None and prior != resource:
            raise ValueError("inventory generation contains conflicting resource observations")
        indexed[resource.resource_id] = resource
    return indexed


def _observation_time(resource: ResourceRecord | None) -> datetime | None:
    if resource is None or resource.last_seen is None:
        return None
    try:
        observed_at = datetime.fromisoformat(resource.last_seen.replace("Z", "+00:00"))
    except ValueError:
        return None
    return observed_at if observed_at.tzinfo is not None else None


def _verification_receipt(
    *,
    generation: str,
    link: LinkRecord,
    verifier_identity: str,
    verifier_revision: str,
) -> str:
    evidence = link.mapping_evidence
    if evidence is None:
        raise ValueError("verified relationship receipt requires mapping evidence")
    payload = json.dumps(
        {
            "edge": [link.from_id, link.link_type, link.to_id],
            "generation": generation,
            "mapping_receipt_ref": evidence.mapping_receipt_ref,
            "observation_receipt_ref": evidence.observation_receipt_ref,
            "verifier_identity": verifier_identity,
            "verifier_revision": verifier_revision,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _drop(reason: RelationshipDropReason, link: LinkRecord) -> RelationshipDrop:
    evidence = link.mapping_evidence
    return RelationshipDrop(
        reason=reason,
        mapping_id=evidence.mapping_id if evidence is not None else None,
        source_property_path=evidence.source_property_path if evidence is not None else None,
    )


def _canonical_drops(drops: Sequence[RelationshipDrop]) -> tuple[RelationshipDrop, ...]:
    return tuple(
        sorted(
            set(drops),
            key=lambda item: (
                item.reason.value,
                item.mapping_id or "",
                item.source_property_path or "",
            ),
        )
    )


__all__ = [
    "DEFAULT_RELATIONSHIP_VERIFIER_IDENTITY",
    "DEFAULT_RELATIONSHIP_VERIFIER_REVISION",
    "VerifiedInventoryRelationships",
    "verify_inventory_relationships",
]
