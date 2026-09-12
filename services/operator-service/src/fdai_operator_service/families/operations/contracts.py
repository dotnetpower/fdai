"""Dependency contracts for the service-local Operator operations family."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai_service_contracts import OperatorRole


class ProjectionUnavailableError(RuntimeError):
    """An authoritative projection cannot satisfy the bounded read."""


class ProjectionNotFoundError(RuntimeError):
    """An exact projection identity does not exist in the visible source."""


class ProposalConflictError(RuntimeError):
    """An idempotency key already names a different durable proposal."""


@dataclass(frozen=True, slots=True)
class ProjectionQuery:
    """One authenticated, bounded query against an injected projection reader."""

    operation: str
    principal_id: str
    path: Mapping[str, str]
    params: Mapping[str, tuple[str, ...]]
    limit: int
    cursor: str | None
    roles: frozenset[OperatorRole] = frozenset()
    purpose: str = "operations-review"


class ProjectionReader(Protocol):
    """Read authoritative operation projections without provider access in routes."""

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Return a JSON-compatible projection or raise unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class InventoryRelationshipDropClassification:
    """One sanitized mapping-specific relationship coverage gap."""

    reason: str
    mapping_id: str
    source_property_path: str
    source_provider_type: str
    target_provider_type: str
    unavailable_reason: str
    count: int


@dataclass(frozen=True, slots=True)
class InventoryProjectionSourceState:
    """One sanitized independently collected inventory projection source state."""

    source: str
    status: str
    observed_at: datetime | None
    reason: str | None
    scope_digest: str | None = None


@dataclass(frozen=True, slots=True)
class InventoryRelationshipCoverage:
    """Exact counted disposition of every candidate ontology relationship instance.

    ``total_candidates`` MUST equal the sum of ``materialized``,
    ``reviewed_unavailable``, and ``unclassified``. ``complete`` is ``True``
    only when no candidate remains unclassified and the source generation that
    produced this count was itself complete.
    """

    materialized: int
    reviewed_unavailable: int
    unclassified: int
    total_candidates: int
    complete: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("materialized", self.materialized),
            ("reviewed_unavailable", self.reviewed_unavailable),
            ("unclassified", self.unclassified),
            ("total_candidates", self.total_candidates),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(
                    f"inventory relationship coverage {field_name} MUST be a non-negative count"
                )
        if self.total_candidates != (
            self.materialized + self.reviewed_unavailable + self.unclassified
        ):
            raise ValueError(
                "inventory relationship coverage total_candidates MUST equal its counted parts"
            )
        if not isinstance(self.complete, bool):
            raise ValueError("inventory relationship coverage complete MUST be boolean")
        if self.complete and self.unclassified != 0:
            raise ValueError(
                "inventory relationship coverage complete MUST be false with unclassified drops"
            )


@dataclass(frozen=True, slots=True)
class InventoryProviderTypeCount:
    """One bounded provider-native type absent from the reviewed registry."""

    provider_type: str
    count: int

    def __post_init__(self) -> None:
        if not self.provider_type.strip() or len(self.provider_type) > 512:
            raise ValueError("inventory provider type identity is malformed")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 1:
            raise ValueError("inventory provider type count MUST be positive")


@dataclass(frozen=True, slots=True)
class InventoryProviderScopeCoverage:
    """Complete provider-native type accounting for one active snapshot."""

    capture_method: str
    provider_object_count: int
    mapped_provider_object_count: int
    unmapped_provider_object_count: int
    materialized_unmapped_provider_object_count: int
    provider_identity_complete: bool
    provider_type_count: int
    unmapped_provider_types: tuple[InventoryProviderTypeCount, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryImpactContext:
    """Exact active inventory generation and its authoritative observation cutoff."""

    snapshot_id: str
    observed_at: datetime
    relationship_drop_reasons: tuple[str, ...] = ()
    relationship_drop_classifications: tuple[InventoryRelationshipDropClassification, ...] = ()
    projection_source_states: tuple[InventoryProjectionSourceState, ...] = ()
    relationship_coverage: InventoryRelationshipCoverage | None = None
    provider_scope_coverage: InventoryProviderScopeCoverage | None = None


@dataclass(frozen=True, slots=True)
class InventoryImpactEdge:
    """One stored-direction inventory edge visible to a bounded impact read."""

    source: str
    target: str
    link_type: str


@dataclass(frozen=True, slots=True)
class InventoryImpactLinkPage:
    """One deterministic outgoing-link page plus its source truncation state."""

    edges: tuple[InventoryImpactEdge, ...]
    truncated: bool


class InventoryImpactReader(Protocol):
    """Read only the active inventory identities needed for bounded impact traversal."""

    async def read_inventory_impact_context(self) -> InventoryImpactContext | None:
        """Return the active complete inventory generation, if one exists."""
        ...

    async def inventory_resource_exists(self, *, snapshot_id: str, resource_id: str) -> bool:
        """Return whether one exact Resource identity exists in the active snapshot."""
        ...

    async def read_inventory_outgoing_links(
        self,
        *,
        snapshot_id: str,
        source_ids: tuple[str, ...],
        link_types: tuple[str, ...],
        limit: int,
    ) -> InventoryImpactLinkPage:
        """Return stored-direction links from one bounded frontier."""
        ...


UNSELECTABLE_INSTANCE_DIRECTORY_TYPES = frozenset({"authorization.role-assignment"})
AKS_DIAGNOSTIC_STATUSES = frozenset(
    {
        "autoscale_limited",
        "control_plane_unavailable",
        "crash_loop",
        "endpoint_unready",
        "evicted",
        "held",
        "image_pull_failed",
        "node_pressure",
        "networking_unavailable",
        "no_failure_signal",
        "oom_killed",
        "probe_failure_evidence",
        "quota_constrained",
        "resource_pressure",
        "rollout_stalled",
        "scheduling_blocked",
        "storage_blocked",
    }
)
_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class InventoryInstanceResource:
    """One active-snapshot Resource row for bounded instance exploration."""

    resource_id: str
    resource_type: str
    properties: Mapping[str, object]
    last_seen: datetime | None


@dataclass(frozen=True, slots=True)
class InventoryRelationshipEvidence:
    """Allowlisted provider configuration provenance for one inventory relationship."""

    source_identity: str
    source_property_path: str
    mapping_id: str
    evidence_method: str
    freshness_ceiling_seconds: int
    evidence_kind: str = "configuration"
    evidence_cutoff: datetime | None = None


@dataclass(frozen=True, slots=True)
class InventoryInstanceEdge:
    """One instance relationship with optional provider configuration provenance."""

    source: str
    target: str
    link_type: str
    evidence: InventoryRelationshipEvidence | None = None


@dataclass(frozen=True, slots=True)
class InventoryInstanceNeighborhood:
    """One exact root and its bounded bidirectional inventory neighborhood."""

    resources: tuple[InventoryInstanceResource, ...]
    edges: tuple[InventoryInstanceEdge, ...]
    truncated: bool
    truncation_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InventoryInstanceResourcePage:
    """One deterministic active-generation Resource directory page."""

    resources: tuple[InventoryInstanceResource, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class InventoryInstanceActivity:
    """One sanitized durable activity record bound to an exact Resource identity."""

    sequence: int
    action_kind: str
    actor: str
    recorded_at: datetime
    correlation_id: str | None
    facts: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class InventoryInstanceActivityPage:
    """A newest-first bounded activity page with explicit truncation state."""

    activities: tuple[InventoryInstanceActivity, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class InventoryAksDiagnosticReceipt:
    """Strict no-authority AKS evidence receipt safe for Operator projection."""

    principal_class: str
    producer_version: str
    method_version: str
    target_resource_id: str
    target_uid: str
    target_resource_version: str
    ontology_release: str
    cutoff: datetime
    source_cutoffs: Mapping[str, datetime]
    source_revisions: Mapping[str, str]
    status: str
    signals: tuple[str, ...]
    complete: bool
    evidence_gaps: tuple[str, ...]
    conflicts: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    audit_correlation_id: str
    cause_claim_supported: bool = False
    execution_authority: bool = False

    def __post_init__(self) -> None:
        for field_name, value, maximum in (
            ("principal_class", self.principal_class, 64),
            ("producer_version", self.producer_version, 128),
            ("method_version", self.method_version, 128),
            ("target_resource_id", self.target_resource_id, 1_024),
            ("target_uid", self.target_uid, 512),
            ("target_resource_version", self.target_resource_version, 512),
            ("ontology_release", self.ontology_release, 128),
            ("audit_correlation_id", self.audit_correlation_id, 128),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"AKS diagnostic {field_name} exceeds its bound")
        if re.fullmatch(r"sha256:[a-f0-9]{64}", self.ontology_release) is None:
            raise ValueError("AKS diagnostic ontology release is malformed")
        if self.cutoff.tzinfo is None:
            raise ValueError("AKS diagnostic cutoff MUST be timezone-aware")
        if (
            not self.source_cutoffs
            or len(self.source_cutoffs) > 16
            or set(self.source_cutoffs) != set(self.source_revisions)
        ):
            raise ValueError("AKS diagnostic source identities are malformed")
        for source, cutoff in self.source_cutoffs.items():
            revision = self.source_revisions.get(source)
            if (
                _REASON_CODE.fullmatch(source) is None
                or cutoff.tzinfo is None
                or cutoff > self.cutoff
                or not isinstance(revision, str)
                or not revision.strip()
                or len(revision) > 256
            ):
                raise ValueError("AKS diagnostic source evidence is malformed")
        if self.status not in AKS_DIAGNOSTIC_STATUSES or any(
            signal not in AKS_DIAGNOSTIC_STATUSES for signal in self.signals
        ):
            raise ValueError("AKS diagnostic status is malformed")
        if len(self.signals) > len(AKS_DIAGNOSTIC_STATUSES) or len(set(self.signals)) != len(
            self.signals
        ):
            raise ValueError("AKS diagnostic signals exceed their bound")
        if len(self.evidence_gaps) > 32 or len(self.conflicts) > 32:
            raise ValueError("AKS diagnostic evidence reasons exceed their bound")
        if any(
            _REASON_CODE.fullmatch(reason) is None
            for reason in (*self.evidence_gaps, *self.conflicts)
        ):
            raise ValueError("AKS diagnostic evidence reason is malformed")
        if len(set(self.evidence_gaps)) != len(self.evidence_gaps) or len(
            set(self.conflicts)
        ) != len(self.conflicts):
            raise ValueError("AKS diagnostic evidence reasons MUST be unique")
        if len(self.evidence_refs) > 32 or any(
            not ref.strip() or len(ref) > 512 for ref in self.evidence_refs
        ):
            raise ValueError("AKS diagnostic evidence refs exceed their bound")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("AKS diagnostic evidence refs MUST be unique")
        if not isinstance(self.complete, bool):
            raise ValueError("AKS diagnostic completeness MUST be boolean")
        if self.complete and (self.evidence_gaps or self.conflicts):
            raise ValueError("complete AKS diagnostic evidence MUST NOT report gaps or conflicts")
        if self.cause_claim_supported is not False or self.execution_authority is not False:
            raise ValueError(
                "AKS diagnostic receipt MUST NOT grant causation or execution authority"
            )


class InventoryInstanceReader(Protocol):
    """Read the active Resource neighborhood and durable activity without mutation authority."""

    async def read_inventory_impact_context(self) -> InventoryImpactContext | None:
        """Return the active inventory generation shared by graph and Resource rows."""
        ...

    async def read_inventory_instance_neighborhood(
        self,
        *,
        snapshot_id: str,
        root_id: str,
        link_types: tuple[str, ...],
        depth: int,
        limit: int,
    ) -> InventoryInstanceNeighborhood:
        """Return a bounded bidirectional neighborhood and all links among its Resources."""
        ...

    async def read_inventory_instances(
        self,
        *,
        snapshot_id: str,
        search: str | None,
        limit: int,
    ) -> InventoryInstanceResourcePage:
        """Return a bounded active-generation Resource directory page."""
        ...

    async def read_inventory_instance_activity(
        self,
        *,
        resource_id: str,
        limit: int,
    ) -> InventoryInstanceActivityPage:
        """Return sanitized exact-resource audit activity in newest-first order."""
        ...

    async def read_latest_aks_diagnostic_receipt(
        self,
        *,
        resource_id: str,
    ) -> InventoryAksDiagnosticReceipt | None:
        """Return the latest well-formed immutable receipt for one exact Resource."""
        ...


class ReportPdfEncodingError(RuntimeError):
    """A materialized report envelope cannot be encoded without guessing."""


class ReportPdfEncoder(Protocol):
    """Encode one materialized report envelope without analysis or provider access."""

    @property
    def name(self) -> str:
        """Return the advertised report format name."""
        ...

    @property
    def content_type(self) -> str:
        """Return the exact HTTP content type for the encoded bytes."""
        ...

    def encode(self, report: Mapping[str, object]) -> bytes:
        """Return a PDF that contains only values from the supplied envelope."""
        ...


@dataclass(frozen=True, slots=True)
class EventProposal:
    """A non-authoritative event proposal persisted before broker publication."""

    operation: str
    principal_id: str | None
    idempotency_key: str
    correlation_id: str | None
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ProposalReceipt:
    """Durable acceptance receipt that makes no execution claim."""

    request_id: str
    correlation_id: str | None
    dispatch_status: str
    accepted_at: str
    durably_queued: bool = True

    def to_dict(self) -> dict[str, object]:
        """Render the stable proposal acceptance envelope."""
        return {
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "dispatch_status": self.dispatch_status,
            "accepted_at": self.accepted_at,
            "durably_queued": self.durably_queued,
        }


class EventProposalWriter(Protocol):
    """Atomically persist an event proposal and its outbox receipt."""

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        """Return only after the proposal is durably queued."""
        ...


@dataclass(frozen=True, slots=True)
class ReplayQuery:
    """One principal-scoped request for durable ordered stream records."""

    stream: str
    principal_id: str
    after_sequence: int | None
    limit: int


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """One durable SSE record with a monotonic replay sequence."""

    sequence: int
    event: str
    data: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ReplayBatch:
    """A bounded replay page and durable source watermark."""

    events: tuple[ReplayEvent, ...]
    watermark: int


class DurableReplayReader(Protocol):
    """Read persisted stream events; transient fan-out is not authoritative."""

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Return events ordered after the requested durable sequence."""
        ...


class WebhookVerifier(Protocol):
    """Verify a bounded webhook body without exposing secret material."""

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Return true only for an authenticated webhook request."""
        ...


__all__ = [
    "DurableReplayReader",
    "EventProposal",
    "EventProposalWriter",
    "InventoryImpactContext",
    "InventoryImpactEdge",
    "InventoryImpactLinkPage",
    "InventoryImpactReader",
    "InventoryProviderScopeCoverage",
    "InventoryProviderTypeCount",
    "InventoryRelationshipCoverage",
    "InventoryRelationshipDropClassification",
    "ProjectionQuery",
    "ProjectionReader",
    "ProjectionNotFoundError",
    "ProjectionUnavailableError",
    "ReportPdfEncoder",
    "ReportPdfEncodingError",
    "ProposalConflictError",
    "ProposalReceipt",
    "ReplayBatch",
    "ReplayEvent",
    "ReplayQuery",
    "WebhookVerifier",
]
