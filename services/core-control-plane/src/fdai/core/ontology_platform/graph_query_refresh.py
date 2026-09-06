"""Deterministic graph-first refresh policy for secured Resource ObjectSets."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactMetadata,
    state_fact_metadata_values,
)

from .archive_retention import ArchiveHistoryStatus
from .graph_evidence_refresh import (
    GraphEvidenceFreshness,
    GraphEvidenceRefreshDecision,
    GraphEvidenceRefreshInput,
    GraphEvidenceRefreshOutcome,
    GraphQueryIntent,
    decide_graph_evidence_refresh,
)
from .models import ObjectSelectorKind, ObjectSetDefinition
from .query_execution import QueryNodeHeldError
from .query_gateway import SecuredObjectSetQueryGateway, SecuredObjectSetQueryResult


class BoundedGraphLiveRefreshProvider(Protocol):
    """Refresh one already secured exact query without granting observation authority."""

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        secured: SecuredObjectSetQueryResult,
    ) -> bool: ...


class SecuredGraphEvidenceQueryRefresher:
    """Apply the five-outcome policy and perform at most one bounded live refresh."""

    def __init__(
        self,
        *,
        gateway: SecuredObjectSetQueryGateway,
        live_provider: BoundedGraphLiveRefreshProvider | None = None,
        deadline_ms: int = 5_000,
        live_read_budget_ms: int = 3_000,
        projection_budget_ms: int = 1_000,
    ) -> None:
        if min(deadline_ms, live_read_budget_ms, projection_budget_ms) < 0:
            raise ValueError("graph query refresh budgets MUST NOT be negative")
        self._gateway = gateway
        self._live_provider = live_provider
        self._deadline_ms = deadline_ms
        self._live_read_budget_ms = live_read_budget_ms
        self._projection_budget_ms = projection_budget_ms

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        projection_request: ProjectionRequest,
        secured: SecuredObjectSetQueryResult,
    ) -> SecuredObjectSetQueryResult:
        """Return current graph evidence, refresh once, or hold with stable reasons."""

        if definition.freshness_seconds is None or not _selects_resources(definition):
            return secured
        decision = _decision(
            definition=definition,
            secured=secured,
            live_read_permitted=self._live_provider is not None,
            deadline_ms=self._deadline_ms,
            live_read_budget_ms=self._live_read_budget_ms,
            projection_budget_ms=self._projection_budget_ms,
        )
        if decision.outcome is GraphEvidenceRefreshOutcome.USE_GRAPH:
            return secured
        if decision.outcome is GraphEvidenceRefreshOutcome.REFRESH_THEN_QUERY:
            if self._live_provider is None:  # pragma: no cover - reducer invariant
                raise RuntimeError("graph refresh selected an unavailable live provider")
            if not await self._live_provider.refresh(definition=definition, secured=secured):
                raise QueryNodeHeldError("graph_refresh_unavailable")
            refreshed = await self._gateway.materialize(
                definition,
                projection_request=projection_request,
            )
            refreshed_decision = _decision(
                definition=definition,
                secured=refreshed,
                live_read_permitted=False,
                deadline_ms=0,
                live_read_budget_ms=0,
                projection_budget_ms=0,
            )
            if refreshed_decision.outcome is GraphEvidenceRefreshOutcome.USE_GRAPH:
                return refreshed
            raise QueryNodeHeldError(
                "graph_refresh_incomplete:" + ",".join(refreshed_decision.reason_codes)
            )
        raise QueryNodeHeldError("graph_refresh_hold:" + ",".join(decision.reason_codes))


def _decision(
    *,
    definition: ObjectSetDefinition,
    secured: SecuredObjectSetQueryResult,
    live_read_permitted: bool,
    deadline_ms: int,
    live_read_budget_ms: int,
    projection_budget_ms: int,
) -> GraphEvidenceRefreshDecision:
    metadata, covered_resource_count = _resource_state_metadata(secured)
    resource_count = sum(
        record.object_type == "Resource" for record in secured.materialization.graph.objects
    )
    freshness = _freshness(
        metadata,
        cutoff=secured.receipt.observation_cutoff,
        required_seconds=definition.freshness_seconds or 1,
    )
    return decide_graph_evidence_refresh(
        GraphEvidenceRefreshInput(
            query_intent=GraphQueryIntent.CURRENT,
            requested_ontology_release_digest=secured.receipt.ontology_release.digest,
            graph_ontology_release_digest=secured.receipt.ontology_release.digest,
            graph_available=True,
            graph_freshness=freshness,
            graph_complete=secured.receipt.complete
            and covered_resource_count == resource_count
            and all(item.completeness == 1.0 for item in metadata),
            graph_truncated=secured.receipt.truncated,
            graph_synthetic=any(item.synthetic for item in metadata),
            graph_conflict_count=sum(len(item.conflicts) for item in metadata),
            explicit_live_read=False,
            live_read_permitted=live_read_permitted,
            verified_live_receipt=False,
            live_receipt_principal_scoped=False,
            deadline_remaining_ms=deadline_ms,
            live_read_budget_ms=live_read_budget_ms,
            projection_budget_ms=projection_budget_ms,
            archive_status=ArchiveHistoryStatus.ABSENT,
            archive_principal_scoped=False,
        )
    )


def _selects_resources(definition: ObjectSetDefinition) -> bool:
    return (
        definition.selector.kind is ObjectSelectorKind.OBJECT_TYPE
        and definition.selector.name == "Resource"
    )


def _resource_state_metadata(
    secured: SecuredObjectSetQueryResult,
) -> tuple[tuple[StateFactMetadata, ...], int]:
    metadata: list[StateFactMetadata] = []
    covered_resource_count = 0
    for record in secured.materialization.graph.objects:
        if record.object_type != "Resource":
            continue
        provider_properties = record.properties.get("properties")
        if not isinstance(provider_properties, Mapping):
            continue
        raw = provider_properties.get(STATE_FACT_METADATA_PROPERTY)
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise ValueError("Resource state fact metadata MUST be an object")
        metadata.extend(state_fact_metadata_values(raw))
        covered_resource_count += 1
    return tuple(metadata), covered_resource_count


def _freshness(
    metadata: tuple[StateFactMetadata, ...],
    *,
    cutoff: datetime,
    required_seconds: int,
) -> GraphEvidenceFreshness:
    if not metadata:
        return GraphEvidenceFreshness.UNKNOWN
    for item in metadata:
        allowed_age = min(required_seconds, item.freshness_ceiling_seconds)
        age_seconds = (cutoff - item.evidence_cutoff).total_seconds()
        if age_seconds < 0:
            return GraphEvidenceFreshness.UNKNOWN
        if age_seconds > allowed_age:
            return GraphEvidenceFreshness.STALE
    return GraphEvidenceFreshness.CURRENT


__all__ = [
    "BoundedGraphLiveRefreshProvider",
    "SecuredGraphEvidenceQueryRefresher",
]
