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
    UNVERIFIED_METADATA = "unverified_metadata"


@dataclass(frozen=True, slots=True)
class RelationshipDrop:
    """One bounded explanation for suppressing a provider relationship candidate."""

    reason: RelationshipDropReason
    mapping_id: str | None = None
    source_property_path: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("mapping_id", self.mapping_id),
            ("source_property_path", self.source_property_path),
        ):
            if value is not None and not value.strip():
                raise ValueError(f"RelationshipDrop.{field_name} MUST be non-empty when supplied")


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
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("ProviderRelationshipEvidence.freshness_ceiling_seconds MUST be >= 1")


class InventoryGraphViewNotFoundError(LookupError):
    """Raised by named-view providers for an unknown explicit view id."""


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
    "RelationshipDrop",
    "RelationshipDropReason",
    "ResourceRecord",
]
