"""Inventory - 5th CSP-neutral wire contract; populates the ontology resource graph.

Realizes the contract in ``docs/roadmap/architecture/csp-neutrality.md § 5. Inventory
Contract`` and the ontology model in ``docs/roadmap/architecture/llm-strategy.md §
Ontology Foundation``.

Core code sees only this Protocol; no cloud SDK (`azure-mgmt-*`,
`boto3.client("config")`, `google.cloud.asset`, ...) is imported anywhere
under ``core/`` or ``shared/``. Adapters live under ``delivery/`` or in a
fork's package and are registered at the composition root.

Two operations return CSP-neutral records:

- :meth:`Inventory.full_snapshot` - the initial or periodic
  reconciliation load, emitted as batches of :class:`ResourceRecord` +
  :class:`LinkRecord`. The Azure adapter parallelizes this by sharding
  the query workload by ``Resource.type`` under a bounded semaphore; the
  Protocol does not prescribe how, it only requires that the batches are
  streamed as ``AsyncIterator[InventoryBatch]`` so the ingest pipeline
  can consume them without an unbounded memory buffer.
- :meth:`Inventory.delta` - incremental changes since ``cursor``, driven
  by the provider's native change stream (Azure Activity Log forwarded
  into the event bus, AWS Config item stream, GCP Cloud Asset feed, K8s
  watch). Deltas MUST be idempotent and safe to re-apply.

Any adapter MUST honor the rules in
``docs/roadmap/architecture/csp-neutrality.md § 5``:

- Idempotent upsert into ``ontology_resource`` + ``ontology_link``.
- Fail-closed on partial snapshot: the caller MUST reject a stream that
  ended before ``final=True`` and retain the previous graph.
- Redact / length-bound untrusted vendor properties before returning
  them; the Protocol return type is inert data.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from .state_evidence import LINK_OBSERVATION_METADATA_PROPERTY, LinkObservationMetadata

INVENTORY_RELATIONSHIP_RECONCILIATION_PREFIX = "inventory-relationship-reconciliation:"
UNCLASSIFIED_RESOURCE_TYPE = "unclassified-resource"
_MAX_PROVIDER_TYPES = 10_000
_MAX_PROVIDER_TYPE_LENGTH = 512
_MAX_PROVIDER_OBJECTS = (2**63) - 1


class RelationshipDropReason(StrEnum):
    """Stable fail-closed reasons for a relationship absent from the active graph."""

    AMBIGUOUS_ORIENTATION = "ambiguous_orientation"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    DUPLICATE_EDGE = "duplicate_edge"
    MISSING_INDEPENDENT_VERIFIER = "missing_independent_verifier"
    MISSING_SOURCE_ENDPOINT = "missing_source_endpoint"
    MISSING_TARGET_ENDPOINT = "missing_target_endpoint"
    PARTIAL_GENERATION = "partial_generation"
    STALE_SOURCE_SCHEMA_DIGEST = "stale_source_schema_digest"
    TARGET_TYPE_MISMATCH = "target_type_mismatch"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    UNVERIFIED_METADATA = "unverified_metadata"


class RelationshipUnavailableReason(StrEnum):
    """Stable reason that a suppressed relationship cannot become an active edge."""

    AUTHORIZATION_CHILD_SCOPE_UNMODELED = "authorization_child_scope_unmodeled"
    REFERENCE_NOT_OBSERVED = "reference_not_observed"
    SOURCE_OUTSIDE_ACTIVE_GENERATION = "source_outside_active_generation"
    TARGET_OUTSIDE_ACTIVE_GENERATION = "target_outside_active_generation"
    TARGET_PROVIDER_TYPE_UNMODELED = "target_provider_type_unmodeled"


_ALLOWED_RELATIONSHIP_UNAVAILABLE_REASONS = {
    RelationshipDropReason.MISSING_SOURCE_ENDPOINT: frozenset(
        {RelationshipUnavailableReason.SOURCE_OUTSIDE_ACTIVE_GENERATION}
    ),
    RelationshipDropReason.MISSING_TARGET_ENDPOINT: frozenset(
        {RelationshipUnavailableReason.TARGET_OUTSIDE_ACTIVE_GENERATION}
    ),
    RelationshipDropReason.TARGET_TYPE_MISMATCH: frozenset(
        {
            RelationshipUnavailableReason.AUTHORIZATION_CHILD_SCOPE_UNMODELED,
            RelationshipUnavailableReason.TARGET_PROVIDER_TYPE_UNMODELED,
        }
    ),
    RelationshipDropReason.UNRESOLVED_REFERENCE: frozenset(
        {RelationshipUnavailableReason.REFERENCE_NOT_OBSERVED}
    ),
}


@dataclass(frozen=True, slots=True)
class RelationshipDrop:
    """One bounded explanation for suppressing a provider relationship candidate."""

    reason: RelationshipDropReason
    mapping_id: str | None = None
    source_property_path: str | None = None
    source_provider_type: str | None = None
    target_provider_type: str | None = None
    unavailable_reason: RelationshipUnavailableReason | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("mapping_id", self.mapping_id),
            ("source_property_path", self.source_property_path),
            ("source_provider_type", self.source_provider_type),
            ("target_provider_type", self.target_provider_type),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"RelationshipDrop.{field_name} MUST be non-empty when supplied")
        if self.unavailable_reason is not None and not isinstance(
            self.unavailable_reason, RelationshipUnavailableReason
        ):
            raise ValueError("RelationshipDrop.unavailable_reason MUST be typed")
        if self.unavailable_reason is not None and self.unavailable_reason not in (
            _ALLOWED_RELATIONSHIP_UNAVAILABLE_REASONS.get(self.reason, frozenset())
        ):
            raise ValueError(
                "RelationshipDrop.unavailable_reason is incompatible with its drop reason"
            )

    @property
    def classified_unavailable(self) -> bool:
        """Return whether this non-edge has one validated unavailable disposition."""

        return self.unavailable_reason is not None


@dataclass(frozen=True, slots=True)
class ProviderRelationshipEvidence:
    """Reviewed mapping and provider observation carried before independent verification."""

    mapping_id: str
    mapping_revision: str
    mapping_receipt_ref: str
    provider_identity: str
    source_identity: str
    source_property_path: str
    source_schema_version: str
    source_schema_digest: str
    observed_schema_digest: str
    evidence_method: str
    freshness_ceiling_seconds: int
    endpoint_orientation: str
    provider_owner_id: str
    observation_receipt_ref: str
    source_provider_type: str | None = None
    target_provider_type: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("mapping_id", self.mapping_id),
            ("mapping_revision", self.mapping_revision),
            ("mapping_receipt_ref", self.mapping_receipt_ref),
            ("provider_identity", self.provider_identity),
            ("source_identity", self.source_identity),
            ("source_property_path", self.source_property_path),
            ("source_schema_version", self.source_schema_version),
            ("source_schema_digest", self.source_schema_digest),
            ("observed_schema_digest", self.observed_schema_digest),
            ("evidence_method", self.evidence_method),
            ("endpoint_orientation", self.endpoint_orientation),
            ("provider_owner_id", self.provider_owner_id),
            ("observation_receipt_ref", self.observation_receipt_ref),
        ):
            if not value.strip():
                raise ValueError(f"ProviderRelationshipEvidence.{field_name} MUST be non-empty")
        for optional_field_name, optional_value in (
            ("source_provider_type", self.source_provider_type),
            ("target_provider_type", self.target_provider_type),
        ):
            if optional_value is not None and not optional_value.strip():
                raise ValueError(
                    f"ProviderRelationshipEvidence.{optional_field_name} "
                    "MUST be non-empty when supplied"
                )
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("ProviderRelationshipEvidence.freshness_ceiling_seconds MUST be >= 1")


class InventoryGraphViewNotFoundError(LookupError):
    """Raised by named-view providers for an unknown explicit view id."""


@dataclass(frozen=True, slots=True)
class ProviderTypeCount:
    """One provider-native type omitted from the declared inventory vocabulary."""

    provider_type: str
    count: int

    def __post_init__(self) -> None:
        if not self.provider_type.strip():
            raise ValueError("ProviderTypeCount.provider_type MUST be non-empty")
        if len(self.provider_type) > _MAX_PROVIDER_TYPE_LENGTH:
            raise ValueError("ProviderTypeCount.provider_type exceeds its length bound")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ValueError("ProviderTypeCount.count MUST be an integer")
        if self.count < 1 or self.count > _MAX_PROVIDER_OBJECTS:
            raise ValueError("ProviderTypeCount.count MUST be in [1, 2^63-1]")


@dataclass(frozen=True, slots=True)
class ProviderScopeCoverage:
    """Complete provider-native type accounting for one full snapshot fence."""

    capture_method: str
    provider_object_count: int
    mapped_provider_object_count: int
    provider_type_count: int
    unmapped_provider_types: tuple[ProviderTypeCount, ...] = ()
    materialized_unmapped_provider_object_count: int = 0

    def __post_init__(self) -> None:
        if not self.capture_method.strip():
            raise ValueError("ProviderScopeCoverage.capture_method MUST be non-empty")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                self.provider_object_count,
                self.mapped_provider_object_count,
                self.provider_type_count,
                self.materialized_unmapped_provider_object_count,
            )
        ):
            raise ValueError("ProviderScopeCoverage counts MUST be integers")
        if not 0 <= self.mapped_provider_object_count <= self.provider_object_count:
            raise ValueError(
                "ProviderScopeCoverage.mapped_provider_object_count MUST be within the total"
            )
        if self.provider_object_count > _MAX_PROVIDER_OBJECTS:
            raise ValueError("ProviderScopeCoverage.provider_object_count exceeds its bound")
        if not 0 <= self.provider_type_count <= _MAX_PROVIDER_TYPES:
            raise ValueError("ProviderScopeCoverage.provider_type_count exceeds its bound")
        if (self.provider_object_count == 0) != (
            self.provider_type_count == 0
        ) or self.provider_type_count > self.provider_object_count:
            raise ValueError(
                "ProviderScopeCoverage.provider_type_count MUST match observed objects"
            )
        provider_types = tuple(item.provider_type for item in self.unmapped_provider_types)
        if provider_types != tuple(sorted(set(provider_types))):
            raise ValueError(
                "ProviderScopeCoverage.unmapped_provider_types MUST be unique and sorted"
            )
        if len(provider_types) > self.provider_type_count:
            raise ValueError(
                "ProviderScopeCoverage.unmapped_provider_types exceeds the provider type count"
            )
        if sum(item.count for item in self.unmapped_provider_types) != (
            self.provider_object_count - self.mapped_provider_object_count
        ):
            raise ValueError(
                "ProviderScopeCoverage unmapped counts MUST reconcile with the object totals"
            )
        if self.materialized_unmapped_provider_object_count not in (
            0,
            self.unmapped_provider_object_count,
        ):
            raise ValueError(
                "ProviderScopeCoverage materialized unmapped count MUST be zero or complete"
            )

    @property
    def unmapped_provider_object_count(self) -> int:
        """Return provider objects whose native type has no declared mapping."""
        return self.provider_object_count - self.mapped_provider_object_count

    @property
    def provider_identity_complete(self) -> bool:
        """Return whether every provider-native object has a materialized identity."""
        return (
            self.materialized_unmapped_provider_object_count == self.unmapped_provider_object_count
        )

    def to_metadata(self) -> Mapping[str, object]:
        """Return the canonical JSON-compatible snapshot metadata projection."""
        return {
            "schema_version": "1.1.0",
            "capture_method": self.capture_method,
            "provider_object_count": self.provider_object_count,
            "mapped_provider_object_count": self.mapped_provider_object_count,
            "unmapped_provider_object_count": self.unmapped_provider_object_count,
            "materialized_unmapped_provider_object_count": (
                self.materialized_unmapped_provider_object_count
            ),
            "provider_identity_complete": self.provider_identity_complete,
            "provider_type_count": self.provider_type_count,
            "unmapped_provider_type_count": len(self.unmapped_provider_types),
            "unmapped_provider_types": [
                {"provider_type": item.provider_type, "count": item.count}
                for item in self.unmapped_provider_types
            ],
        }


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    """One CSP-neutral resource observed by the inventory adapter.

    ``resource_id`` is the stable neutral identifier the ontology uses as
    ``ontology_resource.resource_id``. The vendor-native id (ARM path,
    ARN, GCP resource name, K8s uid) rides in ``provider_ref`` for audit
    and is never used as a primary key by ``core/``.
    """

    resource_id: str
    type: str
    props: Mapping[str, Any] = field(default_factory=dict)
    provider_ref: str | None = None
    last_seen: str | None = None
    """RFC 3339 UTC timestamp of the observation; ``None`` when the
    adapter cannot supply one (rare)."""

    def __post_init__(self) -> None:
        for field_name, value in (("resource_id", self.resource_id), ("type", self.type)):
            if not value.strip():
                raise ValueError(f"ResourceRecord.{field_name} MUST be non-empty")
        if not isinstance(self.props, Mapping):
            raise ValueError("ResourceRecord.props MUST be a mapping")
        if self.provider_ref is not None and not self.provider_ref.strip():
            raise ValueError("ResourceRecord.provider_ref MUST be non-empty when supplied")
        if self.last_seen is not None:
            try:
                parsed = datetime.fromisoformat(self.last_seen.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "ResourceRecord.last_seen MUST be timezone-aware RFC 3339"
                ) from exc
            if parsed.tzinfo is None:
                raise ValueError("ResourceRecord.last_seen MUST be timezone-aware RFC 3339")


@dataclass(frozen=True, slots=True)
class LinkRecord:
    """One CSP-neutral Resource→Resource link observed by the inventory adapter.

    ``from_type`` and ``to_type`` are the exact provider-neutral resource types
    carried by the endpoint ``ResourceRecord`` values in the same promoted
    observation. Projection rejects a mismatch instead of accepting a link whose
    endpoint meaning conflicts with the resource graph.

    ``link_type`` MUST be a name registered in
    ``shared/contracts/ontology/link-type.json`` (P1: ``contains`` /
    ``attached_to`` / ``depends_on``; P3+: ``peered_with`` /
    ``routes_to``). Unknown link types MUST be dropped and reported
    upstream - the Protocol does not enforce the registry itself, but
    the caller (event-ingest) MUST validate before writing.
    """

    from_id: str
    from_type: str
    link_type: str
    to_id: str
    to_type: str
    link_props: Mapping[str, Any] = field(default_factory=dict)
    mapping_evidence: ProviderRelationshipEvidence | None = None
    observation_metadata: LinkObservationMetadata | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("from_id", self.from_id),
            ("from_type", self.from_type),
            ("link_type", self.link_type),
            ("to_id", self.to_id),
            ("to_type", self.to_type),
        ):
            if not value.strip():
                raise ValueError(f"LinkRecord.{field_name} MUST be non-empty")
        if not isinstance(self.link_props, Mapping):
            raise ValueError("LinkRecord.link_props MUST be a mapping")
        if self.mapping_evidence is not None and not isinstance(
            self.mapping_evidence, ProviderRelationshipEvidence
        ):
            raise ValueError("LinkRecord.mapping_evidence MUST be typed evidence")
        if self.observation_metadata is not None and not isinstance(
            self.observation_metadata, LinkObservationMetadata
        ):
            raise ValueError("LinkRecord.observation_metadata MUST be typed metadata")
        if LINK_OBSERVATION_METADATA_PROPERTY in self.link_props:
            raise ValueError("LinkRecord.link_props MUST NOT contain reserved observation metadata")


@dataclass(frozen=True, slots=True)
class InventoryBatch:
    """One batch of resources + links returned by ``full_snapshot`` / ``delta``.

    Batches are streamed; a caller MUST NOT rely on any batch to be
    "complete" for a resource type. Idempotency is by
    ``(resource_id)`` for resources and ``(from_id, link_type, to_id)``
    for links.
    """

    resources: tuple[ResourceRecord, ...] = ()
    links: tuple[LinkRecord, ...] = ()
    relationship_drops: tuple[RelationshipDrop, ...] = ()
    cursor: str | None = None
    """Adapter-defined opaque cursor advanced by this batch. Passed back
    to :meth:`Inventory.delta` on the next incremental pull."""
    final: bool = False
    """``True`` only on the last batch of a successful ``full_snapshot``
    call. The caller uses this as the atomic-promote fence - a stream
    that ends without a ``final=True`` batch MUST be discarded."""
    relationship_reconciliation_after: str | None = None
    """RFC 3339 observation time after which relationship coverage is incomplete.

    A delta adapter sets this only when its native change signal proves a
    resource changed but cannot reconstruct the resource's complete links. The
    scheduler uses it to request an authoritative ``full_snapshot``; consumers
    must not infer or delete relationships from this marker alone.
    """
    provider_scope_coverage: ProviderScopeCoverage | None = None
    """Complete provider-native accounting, allowed only on the final fence."""

    def __post_init__(self) -> None:
        if self.provider_scope_coverage is not None and not self.final:
            raise ValueError("InventoryBatch.provider_scope_coverage requires final=True")


@runtime_checkable
class Inventory(Protocol):
    """CSP-neutral resource-graph adapter (5th wire-level contract).

    Async by default - every real backend is I/O-bound (ARG HTTPS, AWS
    Config, GCP Cloud Asset REST, K8s apiserver list-watch). Sync is
    reserved for pure-CPU seams elsewhere; forcing sync here would
    block the event loop under Kafka poll.
    """

    def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:
        """Parallel initial or reconciliation load.

        Adapters MUST shard the workload by ``resource_type`` (and
        further by scope where needed) under a bounded semaphore so a
        large tenant does not exhaust the API budget. The returned
        stream ends with a batch whose ``final=True``.

        ``since`` is optional and adapter-defined; when supplied it MAY
        be used to skip resources whose ``last_seen`` is at least that
        recent (an optimization, not a substitute for :meth:`delta`).
        """
        ...

    def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:
        """Incremental changes since ``cursor``.

        Deltas MUST be idempotent (safe to re-apply on retry) and
        stream in ontology-neutral records. Native provider change
        signals are forwarded into a Kafka topic and consumed exactly
        like any other ``Signal`` - see
        ``docs/roadmap/architecture/csp-neutrality.md § 5``.
        """
        ...


class EmptyInventory:
    """Upstream default binding - an inventory with no resources.

    Symmetric to :class:`~fdai.shared.providers.metric.NoopMetricProvider`:
    ``full_snapshot`` yields only the ``final=True`` fence (a valid empty
    graph) and ``delta`` yields the same, so downstream consumers can be
    authored against a stable interface. Dev / local-fake runs keep this
    binding; a real Azure Resource Graph adapter is wired at the
    composition root via ``bind_azure_inventory``.
    """

    async def full_snapshot(self, since: str | None = None) -> AsyncIterator[InventoryBatch]:  # noqa: ARG002 - Protocol conformance
        yield InventoryBatch(final=True)

    async def delta(self, cursor: str) -> AsyncIterator[InventoryBatch]:  # noqa: ARG002 - Protocol conformance
        yield InventoryBatch(final=True)


__all__ = [
    "EmptyInventory",
    "Inventory",
    "InventoryBatch",
    "InventoryGraphViewNotFoundError",
    "LinkRecord",
    "ProviderRelationshipEvidence",
    "ProviderScopeCoverage",
    "ProviderTypeCount",
    "RelationshipDrop",
    "RelationshipDropReason",
    "ResourceRecord",
    "UNCLASSIFIED_RESOURCE_TYPE",
]
