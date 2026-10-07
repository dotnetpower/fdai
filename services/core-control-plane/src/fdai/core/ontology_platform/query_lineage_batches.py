"""Bounded multi-root lineage reads for collection-anchored relations."""

from __future__ import annotations

from fdai_service_contracts.ontology_query import EvidenceAuthority, content_digest

from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmissionProvider

from .graph_query_refresh import SecuredGraphEvidenceQueryRefresher
from .models import ObjectSetDefinition, ObjectTraversal, RelationshipTraversalDefinition
from .query_execution import QueryNodeHeldError, QueryNodeResult
from .query_gateway import SecuredObjectSetQueryGateway, SecuredObjectSetQueryResult
from .query_receipt_authority import SecuredQueryReceiptAuthority, secured_query_scope_digest
from .query_traversal_tables import relationship_lineage_table
from .query_values import QueryTable

LINEAGE_ROOT_BATCH = 32
LINEAGE_READ_BUDGET = 64


async def batched_lineage_result(
    traversal: RelationshipTraversalDefinition,
    root_ids: tuple[str, ...],
    *,
    dependency: QueryTable,
    base_evidence_refs: tuple[str, ...],
    gateway: SecuredObjectSetQueryGateway,
    request: ProjectionRequest,
    receipt_authority: SecuredQueryReceiptAuthority | None,
    decision_evidence: DecisionEvidenceAdmissionProvider | None,
    graph_refresher: SecuredGraphEvidenceQueryRefresher | None,
    root_batch: int = LINEAGE_ROOT_BATCH,
    read_budget: int = LINEAGE_READ_BUDGET,
) -> QueryNodeResult:
    """Read lineage in root batches under one generation and bounded read budget."""

    pending = [
        root_ids[start : start + root_batch] for start in range(0, len(root_ids), root_batch)
    ]
    tables: list[QueryTable] = []
    digests: list[str] = []
    reasons: list[str] = []
    reads = 0
    while pending:
        batch = pending.pop(0)
        if reads >= read_budget:
            reasons.append("lineage_read_budget")
            break
        reads += 1
        definition = ObjectSetDefinition(
            selector=traversal.selector,
            traversal=ObjectTraversal(
                link_types=traversal.link_types,
                direction=traversal.direction,
                max_depth=traversal.max_depth,
            ),
            root_ids=batch,
            as_of=traversal.as_of,
            purpose=traversal.purpose,
            limit=traversal.limit,
            freshness_seconds=traversal.freshness_seconds,
        )
        secured = await gateway.materialize(definition, projection_request=request)
        secured = await _refresh_result(
            secured,
            definition=definition,
            request=request,
            refresher=graph_refresher,
            expected_generation=dependency.source_generation,
        )
        if secured.receipt.truncated and len(batch) > 1:
            middle = len(batch) // 2
            pending[:0] = [batch[:middle], batch[middle:]]
            continue
        if receipt_authority is not None:
            await _issue_result(
                receipt_authority,
                secured,
                provider=decision_evidence,
            )
        digests.append(secured.receipt.projected_result_digest)
        table = relationship_lineage_table(
            secured,
            root_ids=batch,
            link_type=traversal.link_types[0],
            direction=traversal.direction,
            max_depth=traversal.max_depth,
            endpoint_predicates=traversal.endpoint_predicates,
        )
        if not table.complete and table.truncation_reason is not None:
            reasons.append(table.truncation_reason)
        tables.append(table)
    generations = {table.source_generation for table in tables}
    if len(generations) > 1:
        raise QueryNodeHeldError("query_source_generation_conflict")
    rows = tuple(row for table in tables for row in table.rows)
    merged = QueryTable(
        rows=rows,
        complete=not reasons,
        truncation_reason="+".join(dict.fromkeys(reasons)) if reasons else None,
        source_generation=next(iter(generations), dependency.source_generation),
    )
    batch_digest = content_digest({"object_sets": sorted(digests)})
    return QueryNodeResult(
        value=merged,
        evidence_refs=base_evidence_refs
        + (
            f"ontology-object-set-batch:{batch_digest}",
            f"ontology-query-table:{merged.digest}",
        ),
        authority=EvidenceAuthority.SERVER_INVENTORY_GRAPH,
    )


async def _refresh_result(
    secured: SecuredObjectSetQueryResult,
    *,
    definition: ObjectSetDefinition,
    request: ProjectionRequest,
    refresher: SecuredGraphEvidenceQueryRefresher | None,
    expected_generation: str | None,
) -> SecuredObjectSetQueryResult:
    if definition.freshness_seconds is not None:
        if refresher is None:
            raise QueryNodeHeldError("graph_freshness_unavailable")
        secured = await refresher.refresh(
            definition=definition,
            projection_request=request,
            secured=secured,
        )
    if expected_generation is not None and secured.receipt.source_generation != expected_generation:
        raise QueryNodeHeldError("query_source_generation_conflict")
    return secured


async def _issue_result(
    authority: SecuredQueryReceiptAuthority,
    result: SecuredObjectSetQueryResult,
    *,
    provider: DecisionEvidenceAdmissionProvider | None,
) -> None:
    admission = None
    if provider is not None:
        receipt = result.receipt
        admission = await provider.admit(
            evidence_digest=receipt.projected_result_digest,
            scope_digest=secured_query_scope_digest(receipt),
            purpose_id=receipt.purpose,
            source_revision=receipt.ontology_release.digest,
        )
    authority.issue(result, admission)


__all__ = ["LINEAGE_ROOT_BATCH", "batched_lineage_result"]
