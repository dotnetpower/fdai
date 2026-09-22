"""PostgreSQL and unavailable adapters for non-IAM Operator route families."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import cast

from fdai_service_contracts import OperatorRole, RuleSearchProjection, rule_search_query_digest
from starlette.exceptions import HTTPException

from fdai_operator_service.context_selection_projection import (
    project_context_selection_comparisons,
)
from fdai_operator_service.conversation_family_adapters import (
    PostgresConversationAdapters,
    UnavailableConversationAdapters,
)
from fdai_operator_service.families.aks_commerce import (
    AksCommerceFamilyDependencies,
    StateStoreAksCommerceProjectionReader,
    UnavailableAksCommerceProjectionReader,
)
from fdai_operator_service.families.conversation.contracts import (
    JsonObject,
)
from fdai_operator_service.families.conversation.postgres_document_refs import (
    build_postgres_document_context_resolver,
)
from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowOperation,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
)
from fdai_operator_service.family_adapter_values import mapping as _mapping
from fdai_operator_service.operations_family_adapters import (
    PostgresOperationsAdapters,
    UnavailableOperationsAdapters,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProcessNotVisibleError,
    PostgresProposalConflict,
)
from fdai_operator_service.postgres_semantic_turn_store import rule_search_projection_key
from fdai_operator_service.process_transition_projection import (
    ProcessControlUnavailableError,
    ProcessTransitionDeniedError,
)
from fdai_operator_service.rule_activation_notice import rule_activation_proposal_revision
from fdai_operator_service.workflow_catalog_projection import (
    _best_practice_catalog_payload,
    _caf_catalog_payload,
    _mcsb_catalog_payload,
    _promotion_gate_payload,
    _rule_catalog_payload,
    _rule_findings_summary_payload,
    _wara_catalog_payload,
    rule_activation_history_payload,
    rule_activation_status_payload,
)


@dataclass(frozen=True, slots=True)
class PostgresWorkflowAdapters:
    """Read workflow projections and durably queue shadow-only workflow proposals."""

    store: PostgresFamilyStore

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        """Read a revisioned authoritative workflow projection."""
        joined_revision: str | None = None
        try:
            if request.operation is WorkflowOperation.CONTEXT_SELECTION_COMPARISON_LIST:
                return await self._read_context_selection_comparisons(request)
            if request.operation is WorkflowOperation.RULE_SEARCH:
                query_digest = rule_search_query_digest(request.body)
                stored = await self.store.read_rule_search_projection(
                    principal_id=request.principal_id,
                    query_digest=query_digest,
                )
                projection_key = rule_search_projection_key(
                    request.principal_id,
                    query_digest,
                )
                payload_value = stored.get("data")
                if not isinstance(payload_value, dict):
                    raise HTTPException(
                        status_code=503,
                        detail="authoritative Rule search projection is malformed",
                    )
                payload = RuleSearchProjection.model_validate(payload_value).model_dump(mode="json")
            elif request.operation in {
                WorkflowOperation.RULE_LIST,
                WorkflowOperation.RULE_DETAIL,
            }:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.RULE_LIST.value,
                )
                projection_key = "operator-projection:workflow:rule.list"
                payload = _rule_catalog_payload(stored, request)
            elif request.operation is WorkflowOperation.RULE_FINDINGS_SUMMARY:
                summary_key = "operator-projection:workflow:rule.findings-summary"
                summary = await self.store.read_state(summary_key)
                if summary is None:
                    stored = await self.store.read_projection(
                        family="workflow",
                        operation=WorkflowOperation.RULE_LIST.value,
                    )
                    projection_key = "operator-projection:workflow:rule.list"
                    payload = {"evaluated": False, "counts": {}}
                else:
                    stored = summary
                    projection_key = summary_key
                    payload = _rule_findings_summary_payload(summary)
            elif request.operation is WorkflowOperation.RULE_FINDINGS:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.RULE_LIST.value,
                )
                projection_key = "operator-projection:workflow:rule.list"
                detail = _rule_catalog_payload(stored, request)
                payload = {
                    "rule_id": detail["id"],
                    "origin": detail["origin"],
                    "evaluated": False,
                    "findings": [],
                }
            elif request.operation is WorkflowOperation.RULE_ACTIVATION_STATUS:
                pointer = await self.store.read_state("rule-activation:current")
                if pointer is None:
                    raise HTTPException(
                        status_code=503,
                        detail="authoritative Rule activation projection is unavailable",
                    )
                generation_id = pointer.get("generation_id")
                if not isinstance(generation_id, str):
                    raise HTTPException(
                        status_code=503,
                        detail="authoritative Rule activation projection is malformed",
                    )
                generation = await self.store.read_state(
                    f"rule-activation:generation:{generation_id}"
                )
                if generation is None:
                    raise HTTPException(
                        status_code=503,
                        detail="authoritative Rule activation generation is unavailable",
                    )
                request_page = await self.store.read_state_page(
                    prefix="rule-activation:request:",
                    limit=200,
                )
                result_page = await self.store.read_state_page(
                    prefix="rule-activation:result:",
                    limit=200,
                )
                stored = pointer
                projection_key = "rule-activation:current"
                payload = rule_activation_status_payload(
                    pointer,
                    generation,
                    tuple(record.value for record in request_page.records),
                    tuple(record.value for record in result_page.records),
                    pending_truncated=request_page.truncated or result_page.truncated,
                )
                joined_revision = hashlib.sha256(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode()
                ).hexdigest()
            elif request.operation is WorkflowOperation.RULE_ACTIVATION_HISTORY:
                page = await self.store.read_state_page(
                    prefix="rule-activation:result:",
                    limit=request.limit or 50,
                )
                rule_id = request.path_parameters.get("rule_id", "")
                records = tuple(record.value for record in page.records)
                payload = rule_activation_history_payload(
                    records,
                    rule_id=rule_id,
                    truncated=page.truncated,
                )
                revision_payload = [record.value.get("result", {}) for record in page.records]
                stored = {
                    "_revision": hashlib.sha256(
                        json.dumps(
                            revision_payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            default=str,
                        ).encode()
                    ).hexdigest()
                }
                projection_key = "rule-activation:result:"
            elif request.operation in {
                WorkflowOperation.BEST_PRACTICE_LIST,
                WorkflowOperation.BEST_PRACTICE_DETAIL,
            }:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.BEST_PRACTICE_LIST.value,
                )
                projection_key = "operator-projection:workflow:best-practice.list"
                payload = _best_practice_catalog_payload(stored, request)
            elif request.operation in {
                WorkflowOperation.CAF_LIST,
                WorkflowOperation.CAF_DETAIL,
            }:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.CAF_LIST.value,
                )
                projection_key = "operator-projection:workflow:caf.list"
                payload = _caf_catalog_payload(stored, request)
            elif request.operation in {
                WorkflowOperation.WARA_LIST,
                WorkflowOperation.WARA_DETAIL,
            }:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.WARA_LIST.value,
                )
                projection_key = "operator-projection:workflow:wara.list"
                payload = _wara_catalog_payload(stored, request)
            elif request.operation in {
                WorkflowOperation.MCSB_LIST,
                WorkflowOperation.MCSB_DETAIL,
            }:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=WorkflowOperation.MCSB_LIST.value,
                )
                projection_key = "operator-projection:workflow:mcsb.list"
                payload = _mcsb_catalog_payload(stored, request)
            elif request.operation is WorkflowOperation.PROMOTION_GATE_LIST:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=request.operation.value,
                )
                modes = await self.store.read_action_promotion_modes()
                projection_key = "operator-projection:workflow:promotion-gate.list"
                payload = _promotion_gate_payload(stored, modes)
                joined_revision = hashlib.sha256(
                    json.dumps(
                        {
                            "catalog_revision": stored.get("_revision"),
                            "modes": modes,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
            else:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=request.operation.value,
                )
                projection_key = f"operator-projection:workflow:{request.operation.value}"
                payload = dict(stored)
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        revision = joined_revision or stored.get("_revision", stored.get("revision"))
        if not isinstance(revision, str) or not revision:
            raise HTTPException(
                status_code=503,
                detail="authoritative workflow projection has no revision",
            )
        return WorkflowReadResult(
            payload=cast(JsonObject, payload),
            provenance=ProjectionProvenance(
                source_ref=f"state_kv:{projection_key}",
                revision=revision,
            ),
        )

    async def _read_context_selection_comparisons(
        self,
        request: WorkflowReadRequest,
    ) -> WorkflowReadResult:
        """Project bounded durable shadow comparisons as a read-only panel."""
        records, revision = await self.store.read_context_selection_comparisons(
            limit=request.limit or 100,
        )
        return WorkflowReadResult(
            payload=project_context_selection_comparisons(records),
            provenance=ProjectionProvenance(
                source_ref="state_kv:context-selection:evaluation",
                revision=revision,
            ),
        )

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        """Append a typed workflow proposal without promoting or executing it."""
        try:
            if proposal.operation in {
                WorkflowOperation.WORKFLOW_RESUME_REQUEST,
                WorkflowOperation.WORKFLOW_CANCEL_REQUEST,
                WorkflowOperation.WORKFLOW_RETRY_REQUEST,
            }:
                process_id = proposal.path_parameters.get("process_id", "")
                roles = frozenset(OperatorRole(role) for role in proposal.principal_roles)
                stored = await self.store.append_guarded_workflow_transition_proposal(
                    operation=proposal.operation.value,
                    process_id=process_id,
                    principal_id=proposal.principal_id,
                    expected_revision=proposal.expected_revision,
                    principal_roles=roles,
                    idempotency_key=proposal.idempotency_key,
                    proposal_payload=_mapping(asdict(proposal)),
                )
            else:
                stored = await self.store.append_proposal(
                    family="workflow",
                    operation=proposal.operation.value,
                    principal_id=proposal.principal_id,
                    idempotency_key=proposal.idempotency_key,
                    payload=_mapping(asdict(proposal)),
                )
        except PostgresProposalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PostgresProcessNotVisibleError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ProcessControlUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ProcessTransitionDeniedError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        revision = stored.accepted_at
        if proposal.operation is WorkflowOperation.RULE_ACTIVATION_REQUEST:
            key_digest = hashlib.sha256(proposal.idempotency_key.encode()).hexdigest()
            revision = rule_activation_proposal_revision(
                f"operator-proposal:workflow:{key_digest}",
                stored.record,
            )
        return WorkflowProposalReceipt(
            proposal_id=stored.proposal_id,
            revision=revision,
            duplicate=stored.duplicate,
        )


class UnavailableWorkflowAdapters:
    """Fail every workflow route closed while preserving route registration."""

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        del request
        raise HTTPException(status_code=503, detail="authoritative workflow store is unavailable")

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="workflow proposal outbox is unavailable")


__all__ = [
    "AksCommerceFamilyDependencies",
    "PostgresConversationAdapters",
    "PostgresOperationsAdapters",
    "PostgresWorkflowAdapters",
    "StateStoreAksCommerceProjectionReader",
    "UnavailableAksCommerceProjectionReader",
    "UnavailableConversationAdapters",
    "UnavailableOperationsAdapters",
    "UnavailableWorkflowAdapters",
    "build_postgres_document_context_resolver",
]
