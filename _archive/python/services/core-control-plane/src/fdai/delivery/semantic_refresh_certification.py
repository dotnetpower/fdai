"""Certify five audited graph-refresh states against one active inventory generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from fdai_service_contracts.ontology_query import content_digest
from psycopg.rows import dict_row

from fdai.core.ontology_platform.graph_query_refresh import (
    SecuredGraphEvidenceQueryRefresher,
)
from fdai.core.ontology_platform.graph_refresh_audit import (
    GraphEvidenceRefreshAuditRecord,
    GraphEvidenceStatus,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_execution import QueryNodeHeldError
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.delivery.inventory_live_evidence import (
    InventoryLiveEvidenceWriter,
    LiveEvidenceWriteThroughReceipt,
)
from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig
from fdai.delivery.persistence.postgres_inventory_delta import PostgresInventoryDeltaProjector
from fdai.delivery.persistence.postgres_inventory_snapshot import (
    PostgresInventorySnapshotStoreConfig,
)
from fdai.shared.contracts.models import CeilingRole, OntologyReleaseRef
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadEvidenceRecord,
    ResolvedResource,
)
from fdai.shared.providers.state_evidence import (
    STATE_FACT_METADATA_PROPERTY,
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)


@dataclass(frozen=True, slots=True)
class ActiveCertificationResource:
    """One exact Resource selected from the active sandbox generation."""

    generation: str
    resource_id: str
    resource_type: str
    name: str


class _AuditSink:
    def __init__(self, store: PostgresStateStore, *, recorded_at: datetime) -> None:
        self._store = store
        self._recorded_at = recorded_at
        self.records: list[GraphEvidenceRefreshAuditRecord] = []

    async def record(self, record: GraphEvidenceRefreshAuditRecord) -> None:
        self.records.append(record)
        await self._store.append_audit_entry(
            {
                "kind": "semantic.graph_evidence_refresh",
                "tier": "t0",
                "actor": "Bragi",
                "accountable_agent": "Bragi",
                "recorded_at": self._recorded_at.isoformat(),
                "audit_id": f"{record.digest}:{len(self.records)}",
                "record_digest": record.digest,
                "phase": record.phase.value,
                "evidence_status": record.evidence_status.value,
                "decision": record.decision.outcome.value,
                "reason_codes": list(record.decision.reason_codes),
                "decision_digest": record.decision.digest,
                "ontology_release_digest": record.ontology_release_digest,
                "principal_scope_digest": record.principal_scope_digest,
                "source_revisions": list(record.source_revisions),
                "observation_authority": False,
                "mutation_authority": False,
                "execution_authority": False,
            }
        )


class _Gateway:
    def __init__(self, refreshed: SecuredObjectSetQueryResult) -> None:
        self.refreshed = refreshed
        self.calls = 0

    async def materialize(
        self,
        definition: ObjectSetDefinition,
        *,
        projection_request: ProjectionRequest,
    ) -> SecuredObjectSetQueryResult:
        del definition, projection_request
        self.calls += 1
        return self.refreshed


class _LiveProvider:
    def __init__(
        self,
        *,
        resource: ActiveCertificationResource,
        writer: InventoryLiveEvidenceWriter,
        scope_ref: str,
        evidence_ref: str,
        observed_at: datetime,
        ontology_release_digest: str,
    ) -> None:
        self._resource = resource
        self._writer = writer
        self._scope_ref = scope_ref
        self._evidence_ref = evidence_ref
        self._observed_at = observed_at
        self._ontology_release_digest = ontology_release_digest
        self.calls = 0
        self.receipt: LiveEvidenceWriteThroughReceipt | None = None

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        secured: SecuredObjectSetQueryResult,
    ) -> bool:
        del definition
        self.calls += 1
        resources = secured.materialization.graph.objects
        if self.calls != 1 or len(resources) != 1 or resources[0].id != self._resource.resource_id:
            return False
        evidence = ReadEvidenceEnvelope(
            status=EvidenceStatus.MATCHED,
            authority="azure.resource_graph.certification",
            resource_ref=self._resource.resource_id,
            observed_at=self._observed_at,
            freshness=EvidenceFreshness.LIVE,
            truncated=False,
            records=(
                ReadEvidenceRecord(
                    occurred_at=self._observed_at,
                    status="observed",
                    state="observed",
                ),
            ),
            evidence_refs=(self._evidence_ref,),
        )
        self.receipt = await self._writer.publish(
            resource=ResolvedResource(
                resource_ref=self._resource.resource_id,
                scope_ref=self._scope_ref,
                name=self._resource.name,
                resource_type=self._resource.resource_type,
            ),
            evidence=evidence,
            ontology_release_digest=self._ontology_release_digest,
        )
        return self.receipt.published


async def certify_semantic_graph_refresh(
    *,
    dsn: str,
    scope_ref: str,
    source_revision: str,
    request_id: str,
    provider_evidence_digest: str,
) -> dict[str, object]:
    """Audit five states and verify one bounded canonical live write-through."""

    now = datetime.now(UTC)
    resource = await _load_active_resource(dsn)
    ontology_release_digest = _sha256({"source_revision": source_revision})
    principal_scope_digest = content_digest(
        {
            "request_id": request_id,
            "purpose": "operations-review",
            "role": "owner",
        }
    )
    state_store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    auditor = _AuditSink(state_store, recorded_at=now)
    request = ProjectionRequest(
        caller_role=CeilingRole.OWNER,
        declared_purposes=frozenset({"operations-review"}),
        principal_scope_digest=principal_scope_digest,
    )

    complete = _secured(
        resource,
        now=now,
        age_seconds=1,
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    await _refresh(complete, request=request, auditor=auditor)
    incomplete = _secured(
        resource,
        now=now,
        age_seconds=1,
        completeness=0.5,
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    await _refresh(incomplete, request=request, auditor=auditor)
    conflicting = _secured(
        resource,
        now=now,
        age_seconds=1,
        conflicts=("certification_conflict",),
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    await _refresh(conflicting, request=request, auditor=auditor)
    unavailable = _secured(
        resource,
        now=now,
        age_seconds=1,
        include_metadata=False,
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    await _refresh(unavailable, request=request, auditor=auditor)

    refreshed = _secured(
        resource,
        now=now,
        age_seconds=0,
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    gateway = _Gateway(refreshed)
    provider = _LiveProvider(
        resource=resource,
        writer=InventoryLiveEvidenceWriter(
            ingress=PostgresInventoryDeltaProjector(
                config=PostgresInventorySnapshotStoreConfig(dsn=dsn),
                clock=lambda: now,
            )
        ),
        scope_ref=scope_ref,
        evidence_ref=f"inventory-network:{provider_evidence_digest}",
        observed_at=now,
        ontology_release_digest=ontology_release_digest,
    )
    stale = _secured(
        resource,
        now=now,
        age_seconds=120,
        ontology_release_digest=ontology_release_digest,
        principal_scope_digest=principal_scope_digest,
    )
    result = await SecuredGraphEvidenceQueryRefresher(
        gateway=gateway,
        live_provider=provider,
        auditor=auditor,
    ).refresh(
        definition=stale.materialization.definition,
        projection_request=request,
        secured=stale,
    )
    if (
        result.receipt.principal_scope_digest != principal_scope_digest
        or provider.calls != 1
        or gateway.calls != 1
        or provider.receipt is None
        or not provider.receipt.published
        or not await state_store.verify_chain()
    ):
        raise RuntimeError("semantic graph refresh certification did not converge")
    statuses = tuple(sorted({record.evidence_status.value for record in auditor.records}))
    expected_statuses = tuple(sorted(status.value for status in GraphEvidenceStatus))
    if statuses != expected_statuses:
        raise RuntimeError("semantic graph refresh certification did not preserve five states")
    body: dict[str, object] = {
        "schema_version": "fdai.semantic-graph-refresh-certification.v1",
        "source_revision": source_revision,
        "request_id": request_id,
        "principal_scope_digest": principal_scope_digest,
        "active_generation_digest": _opaque_digest(resource.generation),
        "evidence_statuses": list(statuses),
        "provider_read_count": provider.calls,
        "gateway_requery_count": gateway.calls,
        "write_through_digest": provider.receipt.digest,
        "write_through_outcome": (
            provider.receipt.projector_outcome.value
            if provider.receipt.projector_outcome is not None
            else None
        ),
        "audit_record_digests": [record.digest for record in auditor.records],
        "audit_chain_verified": True,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return {**body, "digest": _sha256(body)}


async def _refresh(
    secured: SecuredObjectSetQueryResult,
    *,
    request: ProjectionRequest,
    auditor: _AuditSink,
) -> None:
    try:
        await SecuredGraphEvidenceQueryRefresher(
            gateway=_Gateway(secured),
            auditor=auditor,
        ).refresh(
            definition=secured.materialization.definition,
            projection_request=request,
            secured=secured,
        )
    except QueryNodeHeldError:
        return


async def _load_active_resource(dsn: str) -> ActiveCertificationResource:
    async with await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row) as connection:
        cursor = await connection.execute(
            """
            SELECT active.snapshot_id, resource.resource_id, resource.resource_type, resource.props
              FROM inventory_active AS active
              JOIN inventory_snapshot_resource AS resource
                ON resource.snapshot_id = active.snapshot_id
             WHERE active.singleton = TRUE
             ORDER BY resource.resource_id
             LIMIT 1
            """
        )
        row = await cursor.fetchone()
    if row is None:
        raise RuntimeError("semantic graph refresh certification requires one active Resource")
    props = row["props"]
    name = props.get("name") if isinstance(props, Mapping) else None
    return ActiveCertificationResource(
        generation=str(row["snapshot_id"]),
        resource_id=str(row["resource_id"]),
        resource_type=str(row["resource_type"]),
        name=str(name) if isinstance(name, str) and name.strip() else "certification-resource",
    )


def _secured(
    resource: ActiveCertificationResource,
    *,
    now: datetime,
    age_seconds: int,
    ontology_release_digest: str,
    principal_scope_digest: str,
    completeness: float = 1.0,
    conflicts: tuple[str, ...] = (),
    include_metadata: bool = True,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=now,
        purpose="operations-review",
        freshness_seconds=60,
        include_relationships=False,
    )
    properties: dict[str, object] = {
        "id": resource.resource_id,
        "name": resource.name,
        "type": resource.resource_type,
        "properties": {},
    }
    if include_metadata:
        metadata = StateFactMetadata(
            lane=StateFactLane.OBSERVED,
            authority=StateFactAuthority.PROVIDER,
            source_identity="azure-resource-graph",
            source_revision=resource.generation,
            effective_at=now - timedelta(seconds=age_seconds),
            recorded_at=now - timedelta(seconds=age_seconds),
            evidence_cutoff=now - timedelta(seconds=age_seconds),
            freshness_ceiling_seconds=300,
            completeness=completeness,
            synthetic=False,
            conflicts=conflicts,
            evidence_refs=(f"inventory-generation:{_opaque_digest(resource.generation)}",),
        )
        properties["properties"] = {STATE_FACT_METADATA_PROPERTY: metadata.to_mapping()}
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id=resource.resource_id,
                    object_type="Resource",
                    properties=properties,
                ),
            ),
            links=(),
        ),
        concrete_types=("Resource",),
        truncated=False,
    )
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=OntologyReleaseRef(
                schema_version="1.0.0",
                digest=ontology_release_digest,
            ),
            projected_result_digest=_projected_result_digest(materialization),
            purpose=definition.purpose,
            caller_role=CeilingRole.OWNER,
            principal_scope_digest=principal_scope_digest,
            observation_cutoff=now,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=True,
            truncated=False,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


def _opaque_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


__all__ = ["ActiveCertificationResource", "certify_semantic_graph_refresh"]
