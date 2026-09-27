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
from .graph_refresh_audit import (
    GraphEvidenceRefreshAuditor,
    GraphEvidenceRefreshAuditRecord,
    GraphEvidenceStatus,
    GraphRefreshAuditPhase,
)
from .models import ObjectSelectorKind, ObjectSetDefinition
from .query_execution import QueryNodeHeldError
from .query_gateway import SecuredObjectSetQueryResult


class BoundedGraphLiveRefreshProvider(Protocol):
    """Refresh one already secured exact query without granting observation authority."""

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        secured: SecuredObjectSetQueryResult,
    ) -> bool: ...


class SecuredGraphQueryGateway(Protocol):
    """Materialize one principal-scoped ObjectSet for bounded re-query."""

    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
    ) -> SecuredObjectSetQueryResult: ...


class SecuredGraphEvidenceQueryRefresher:
    """Apply the five-outcome policy and perform at most one bounded live refresh."""

    def __init__(
        self,
        *,
        gateway: SecuredGraphQueryGateway,
        live_provider: BoundedGraphLiveRefreshProvider | None = None,
        deadline_ms: int = 5_000,
        live_read_budget_ms: int = 3_000,
        projection_budget_ms: int = 1_000,
        auditor: GraphEvidenceRefreshAuditor | None = None,
    ) -> None:
        if min(deadline_ms, live_read_budget_ms, projection_budget_ms) < 0:
            raise ValueError("graph query refresh budgets MUST NOT be negative")
        self._gateway = gateway
        self._live_provider = live_provider
        self._deadline_ms = deadline_ms
        self._live_read_budget_ms = live_read_budget_ms
        self._projection_budget_ms = projection_budget_ms
        self._auditor = auditor

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        projection_request: ProjectionRequest,
        secured: SecuredObjectSetQueryResult,
        freshness_state_keys: tuple[str, ...] | None = None,
    ) -> SecuredObjectSetQueryResult:
        """Return current graph evidence, refresh once, or hold with stable reasons."""

        if freshness_state_keys is not None and (
            not freshness_state_keys
            or len(freshness_state_keys) != len(set(freshness_state_keys))
            or any(not key.strip() for key in freshness_state_keys)
        ):
            raise ValueError("graph freshness state keys MUST be unique and non-empty")
        if definition.freshness_seconds is None:
            return secured
        if not _selects_resources(definition) and not any(
            record.object_type == "Resource" for record in secured.materialization.graph.objects
        ):
            raise QueryNodeHeldError("graph_freshness_unsupported")
        decision, status, revisions = _evaluation(
            definition=definition,
            secured=secured,
            live_read_permitted=self._live_provider is not None,
            deadline_ms=self._deadline_ms,
            live_read_budget_ms=self._live_read_budget_ms,
            projection_budget_ms=self._projection_budget_ms,
            freshness_state_keys=freshness_state_keys,
        )
        await self._audit(
            phase=GraphRefreshAuditPhase.EVALUATED,
            decision=decision,
            status=status,
            revisions=revisions,
            secured=secured,
            projection_request=projection_request,
        )
        if decision.outcome is GraphEvidenceRefreshOutcome.USE_GRAPH:
            return secured
        if decision.outcome is GraphEvidenceRefreshOutcome.REFRESH_THEN_QUERY:
            if self._live_provider is None:  # pragma: no cover - reducer invariant
                raise RuntimeError("graph refresh selected an unavailable live provider")
            if not await self._live_provider.refresh(definition=definition, secured=secured):
                hold_reasons = tuple(
                    reason
                    for reason in decision.reason_codes
                    if reason != "bounded_refresh_available"
                )
                terminal = _terminal_decision(("provider_refresh_unavailable", *hold_reasons))
                await self._audit(
                    phase=GraphRefreshAuditPhase.TERMINAL,
                    decision=terminal,
                    status=GraphEvidenceStatus.UNAVAILABLE,
                    revisions=revisions,
                    secured=secured,
                    projection_request=projection_request,
                )
                raise QueryNodeHeldError("graph_refresh_unavailable:" + ",".join(hold_reasons))
            refreshed = await self._gateway.materialize(
                definition,
                projection_request=projection_request,
            )
            refreshed_decision, refreshed_status, refreshed_revisions = _evaluation(
                definition=definition,
                secured=refreshed,
                live_read_permitted=False,
                deadline_ms=0,
                live_read_budget_ms=0,
                projection_budget_ms=0,
                freshness_state_keys=freshness_state_keys,
            )
            await self._audit(
                phase=GraphRefreshAuditPhase.REQUERY,
                decision=refreshed_decision,
                status=refreshed_status,
                revisions=refreshed_revisions,
                secured=refreshed,
                projection_request=projection_request,
            )
            if refreshed_decision.outcome is GraphEvidenceRefreshOutcome.USE_GRAPH:
                return refreshed
            raise QueryNodeHeldError(
                "graph_refresh_incomplete:" + ",".join(refreshed_decision.reason_codes)
            )
        raise QueryNodeHeldError("graph_refresh_hold:" + ",".join(decision.reason_codes))

    async def _audit(
        self,
        *,
        phase: GraphRefreshAuditPhase,
        decision: GraphEvidenceRefreshDecision,
        status: GraphEvidenceStatus,
        revisions: tuple[str, ...],
        secured: SecuredObjectSetQueryResult,
        projection_request: ProjectionRequest,
    ) -> None:
        if self._auditor is None:
            return
        await self._auditor.record(
            GraphEvidenceRefreshAuditRecord.build(
                phase=phase,
                evidence_status=status,
                decision=decision,
                ontology_release_digest=secured.receipt.ontology_release.digest,
                principal_scope_digest=projection_request.principal_scope_digest,
                source_revisions=revisions,
            )
        )


def _evaluation(
    *,
    definition: ObjectSetDefinition,
    secured: SecuredObjectSetQueryResult,
    live_read_permitted: bool,
    deadline_ms: int,
    live_read_budget_ms: int,
    projection_budget_ms: int,
    freshness_state_keys: tuple[str, ...] | None,
) -> tuple[GraphEvidenceRefreshDecision, GraphEvidenceStatus, tuple[str, ...]]:
    metadata, covered_resource_count = _resource_state_metadata(
        secured,
        freshness_state_keys=freshness_state_keys,
    )
    resource_count = sum(
        record.object_type == "Resource" for record in secured.materialization.graph.objects
    )
    freshness = _freshness(
        metadata,
        cutoff=secured.receipt.observation_cutoff,
        required_seconds=definition.freshness_seconds or 1,
    )
    evidence = GraphEvidenceRefreshInput(
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
    decision = decide_graph_evidence_refresh(evidence)
    return (
        decision,
        _evidence_status(
            evidence=evidence,
            resource_count=resource_count,
            covered_resource_count=covered_resource_count,
        ),
        tuple(sorted({item.source_revision for item in metadata})),
    )


def _evidence_status(
    *,
    evidence: GraphEvidenceRefreshInput,
    resource_count: int,
    covered_resource_count: int,
) -> GraphEvidenceStatus:
    if not evidence.graph_available or resource_count == 0 or covered_resource_count == 0:
        return GraphEvidenceStatus.UNAVAILABLE
    if evidence.graph_conflict_count:
        return GraphEvidenceStatus.CONFLICTING
    if (
        not evidence.graph_complete
        or evidence.graph_truncated
        or evidence.graph_synthetic
        or covered_resource_count != resource_count
    ):
        return GraphEvidenceStatus.INCOMPLETE
    if evidence.graph_freshness is not GraphEvidenceFreshness.CURRENT:
        return GraphEvidenceStatus.STALE
    return GraphEvidenceStatus.COMPLETE


def _terminal_decision(reason_codes: tuple[str, ...]) -> GraphEvidenceRefreshDecision:
    evidence = GraphEvidenceRefreshInput(
        query_intent=GraphQueryIntent.CURRENT,
        requested_ontology_release_digest="sha256:" + ("0" * 64),
        graph_ontology_release_digest="sha256:" + ("0" * 64),
        graph_available=False,
        graph_freshness=GraphEvidenceFreshness.UNAVAILABLE,
        graph_complete=False,
        graph_truncated=False,
        graph_synthetic=False,
        graph_conflict_count=0,
        explicit_live_read=False,
        live_read_permitted=False,
        verified_live_receipt=False,
        live_receipt_principal_scoped=False,
        deadline_remaining_ms=0,
        live_read_budget_ms=0,
        projection_budget_ms=0,
        archive_status=ArchiveHistoryStatus.ABSENT,
        archive_principal_scoped=False,
    )
    decision = decide_graph_evidence_refresh(evidence)
    return GraphEvidenceRefreshDecision(
        outcome=decision.outcome,
        reason_codes=reason_codes,
        digest=_decision_digest(decision.outcome.value, reason_codes),
    )


def _decision_digest(outcome: str, reason_codes: tuple[str, ...]) -> str:
    import hashlib
    import json

    body = {
        "outcome": outcome,
        "reason_codes": reason_codes,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _selects_resources(definition: ObjectSetDefinition) -> bool:
    return (
        definition.selector.kind is ObjectSelectorKind.OBJECT_TYPE
        and definition.selector.name == "Resource"
    )


def _resource_state_metadata(
    secured: SecuredObjectSetQueryResult,
    *,
    freshness_state_keys: tuple[str, ...] | None,
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
        if freshness_state_keys is None:
            metadata.extend(state_fact_metadata_values(raw))
            covered_resource_count += 1
            continue
        candidates = _state_fact_candidates(raw, freshness_state_keys=freshness_state_keys)
        if not candidates:
            continue
        metadata.append(
            max(
                candidates,
                key=lambda item: (
                    item.completeness == 1.0 and not item.synthetic and not item.conflicts,
                    item.evidence_cutoff,
                    item.recorded_at,
                    item.source_identity,
                ),
            )
        )
        covered_resource_count += 1
    return tuple(metadata), covered_resource_count


def _state_fact_candidates(
    raw: Mapping[str, object],
    *,
    freshness_state_keys: tuple[str, ...],
) -> tuple[StateFactMetadata, ...]:
    if "lane" in raw:
        return (StateFactMetadata.from_mapping(raw),) if "state" in freshness_state_keys else ()
    candidates: list[StateFactMetadata] = []
    for key in freshness_state_keys:
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise ValueError("Resource state fact metadata entry MUST be an object")
        candidates.append(StateFactMetadata.from_mapping(value))
    return tuple(candidates)


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
    "SecuredGraphQueryGateway",
    "SecuredGraphEvidenceQueryRefresher",
]
