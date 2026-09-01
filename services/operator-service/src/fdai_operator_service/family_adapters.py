"""PostgreSQL and unavailable adapters for non-IAM Operator route families."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import Counter
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass
from typing import cast

from fdai_service_contracts import OperatorRole, RuleSearchProjection, rule_search_query_digest
from starlette.exceptions import HTTPException

from fdai_operator_service.context_selection import ContextSelectionRegistry
from fdai_operator_service.context_selection_projection import (
    project_context_selection_comparisons,
)
from fdai_operator_service.families.conversation.background_tasks import (
    materialize_background_task,
    open_background_task_stream,
)
from fdai_operator_service.families.conversation.contracts import (
    ConversationEventStream,
    ConversationProposal,
    ConversationQuery,
    ConversationResponse,
    ConversationStreamRequest,
    ConversationUnavailableError,
    JsonObject,
    OutboxReceipt,
    StreamEvent,
)
from fdai_operator_service.families.conversation.conversation_search import (
    materialize_conversation_search,
)
from fdai_operator_service.families.conversation.user_context import (
    materialize_user_context,
)
from fdai_operator_service.families.operations.contracts import (
    EventProposal,
    ProjectionNotFoundError,
    ProjectionQuery,
    ProjectionUnavailableError,
    ProposalConflictError,
    ProposalReceipt,
    ReplayBatch,
    ReplayEvent,
    ReplayQuery,
)
from fdai_operator_service.families.operations.instance_explorer import (
    project_inventory_instance,
    project_inventory_instances,
)
from fdai_operator_service.families.operations.inventory_impact import (
    project_inventory_impact,
)
from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowOperation,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
)
from fdai_operator_service.postgres_family_store import (
    PostgresFamilyStore,
    PostgresFamilyStoreUnavailable,
    PostgresProcessNotVisibleError,
    PostgresProposalConflict,
)
from fdai_operator_service.postgres_read_investigation_replay import (
    PostgresReadInvestigationReplayStore,
)
from fdai_operator_service.postgres_semantic_turn_store import rule_search_projection_key
from fdai_operator_service.process_transition_projection import (
    ProcessControlUnavailableError,
    ProcessTransitionDeniedError,
)


class _ConversationEventIterator(AsyncIterator[StreamEvent]):
    def __init__(self, events: tuple[StreamEvent, ...]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _ConversationEventIterator:
        return self

    async def __anext__(self) -> StreamEvent:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self) -> None:
        """Close the finite authoritative replay iterator."""


@dataclass(frozen=True, slots=True)
class PostgresConversationAdapters:
    """Read conversation projections and append typed proposals through PostgreSQL."""

    store: PostgresFamilyStore

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        """Read an explicitly materialized conversation projection."""
        try:
            background_response = await materialize_background_task(query, store=self.store)
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationUnavailableError(
                "authoritative background task projection is unavailable"
            ) from exc
        if background_response is not None:
            return background_response
        try:
            search_response = await materialize_conversation_search(query, store=self.store)
            if search_response is not None:
                return search_response
            context_response = await materialize_user_context(query, store=self.store)
            if context_response is not None:
                return context_response
            payload = await self.store.read_projection(
                family="conversation",
                operation=query.operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ConversationResponse(body=cast(JsonObject, payload))

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        """Persist one proposal-only conversation intent with duplicate suppression."""
        try:
            stored = await self.store.append_proposal(
                family="conversation",
                operation=proposal.operation,
                principal_id=proposal.scope.subject_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return OutboxReceipt(
            proposal_id=stored.proposal_id,
            duplicate=stored.duplicate,
            response=ConversationResponse(
                body={
                    "accepted": True,
                    "proposal_id": stored.proposal_id,
                    "operation": proposal.operation,
                    "mode": "shadow",
                    "duplicate": stored.duplicate,
                },
                status_code=202,
            ),
        )

    async def open(self, request: ConversationStreamRequest) -> ConversationEventStream:
        """Open a finite replay over durable audit events for the requested operation."""
        try:
            background_stream = await open_background_task_stream(request, store=self.store)
        except PostgresFamilyStoreUnavailable as exc:
            raise ConversationUnavailableError(
                "authoritative background task stream is unavailable"
            ) from exc
        if background_stream is not None:
            return background_stream
        try:
            after = int(request.after_event_id) if request.after_event_id is not None else None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Last-Event-ID MUST be numeric") from exc
        try:
            records = await self.store.replay(
                stream=request.operation,
                principal_id=request.scope.subject_id,
                after_sequence=after,
                limit=500,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _ConversationEventIterator(
            tuple(
                StreamEvent(
                    event=record.event,
                    event_id=str(record.sequence),
                    data=cast(JsonObject, dict(record.data)),
                )
                for record in records
            )
        )


class UnavailableConversationAdapters:
    """Authenticate conversation routes before failing unavailable dependencies closed."""

    async def read(self, query: ConversationQuery) -> ConversationResponse:
        del query
        raise ConversationUnavailableError("authoritative conversation projection is unavailable")

    async def append(self, proposal: ConversationProposal) -> OutboxReceipt:
        del proposal
        raise ConversationUnavailableError("conversation proposal outbox is unavailable")

    async def open(self, request: ConversationStreamRequest) -> _ConversationEventIterator:
        del request
        raise ConversationUnavailableError("conversation event stream is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresWorkflowAdapters:
    """Read workflow projections and durably queue shadow-only workflow proposals."""

    store: PostgresFamilyStore

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        """Read a revisioned authoritative workflow projection."""
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
            else:
                stored = await self.store.read_projection(
                    family="workflow",
                    operation=request.operation.value,
                )
                projection_key = f"operator-projection:workflow:{request.operation.value}"
                payload = dict(stored)
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        revision = stored.get("_revision", stored.get("revision"))
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
        return WorkflowProposalReceipt(
            proposal_id=stored.proposal_id,
            revision=stored.accepted_at,
            duplicate=stored.duplicate,
        )


def _rule_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    rules_value = stored.get("rules")
    details_value = stored.get("details")
    if not isinstance(rules_value, list) or not isinstance(details_value, dict):
        raise HTTPException(status_code=503, detail="authoritative Rule catalog is malformed")
    rules = [item for item in rules_value if isinstance(item, dict)]
    if len(rules) != len(rules_value):
        raise HTTPException(status_code=503, detail="authoritative Rule catalog is malformed")

    if request.operation is WorkflowOperation.RULE_DETAIL:
        rule_id = request.path_parameters.get("rule_id", "")
        origin = request.query.get("origin", "").strip().lower()
        detail = details_value.get(f"{origin}:{rule_id}") if origin else None
        if detail is None:
            detail = next(
                (
                    value
                    for key, value in details_value.items()
                    if isinstance(key, str) and key.endswith(f":{rule_id}")
                ),
                None,
            )
        if not isinstance(detail, dict):
            raise HTTPException(status_code=404, detail=f"unknown rule id {rule_id!r}")
        return dict(detail)

    origin = request.query.get("origin", "").strip().lower()
    category = request.query.get("category", "").strip().lower()
    severity = request.query.get("severity", "").strip().lower()
    source = request.query.get("source", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in rules
        if (not origin or item.get("origin") == origin)
        and (not category or item.get("category") == category)
        and (not severity or item.get("severity") == severity)
        and (not source or item.get("source") == source)
        and (
            not needle or needle in f"{item.get('id', '')}\n{item.get('resource_type', '')}".lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "total": len(rules),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "resource_type_count": len({item.get("resource_type") for item in rules}),
        "facets": {
            "by_origin": _rule_counts(rules, "origin"),
            "by_category": _rule_counts(rules, "category"),
            "by_severity": _rule_counts(rules, "severity"),
            "by_source": _rule_counts(rules, "source"),
        },
        "rules": matched[offset : offset + limit],
    }


def _rule_counts(rules: list[dict[str, object]], field: str) -> dict[str, int]:
    counts = Counter(str(item[field]) for item in rules if isinstance(item.get(field), str))
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _wara_counts(controls: list[dict[str, object]], field: str) -> dict[str, int]:
    values = []
    for item in controls:
        value = item.get(field)
        if isinstance(value, bool):
            values.append(str(value).lower())
        elif isinstance(value, str):
            values.append(value)
    counts = Counter(values)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _best_practice_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    evaluation_source = stored.get("evaluation_source")
    if not isinstance(controls_value, list) or not isinstance(evaluation_source, str):
        raise HTTPException(
            status_code=503,
            detail="authoritative best-practice catalog is malformed",
        )
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value):
        raise HTTPException(
            status_code=503,
            detail="authoritative best-practice catalog is malformed",
        )

    if request.operation is WorkflowOperation.BEST_PRACTICE_DETAIL:
        selected_id = request.path_parameters.get("best_practice_id", "")
        selected = next((item for item in controls if item.get("id") == selected_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown best-practice id {selected_id!r}")
        return dict(selected)

    pillar = request.query.get("pillar", "").strip().lower()
    status = request.query.get("status", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if (not pillar or str(item.get("pillar", "")).lower() == pillar)
        and (not status or str(item.get("status", "")).lower() == status)
        and (
            not needle
            or needle
            in "\n".join(
                str(item.get(field, "")) for field in ("id", "control_id", "title", "rationale")
            ).lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "facets": {
            "by_pillar": _rule_counts(controls, "pillar"),
            "by_status": _rule_counts(controls, "status"),
            "by_severity": _rule_counts(controls, "severity"),
        },
        "controls": [
            {key: value for key, value in item.items() if key not in {"requirements", "provenance"}}
            for item in matched[offset : offset + limit]
        ],
        "evaluation_source": evaluation_source,
    }


def _mcsb_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    catalogs_value = stored.get("catalogs")
    evaluation_source = stored.get("evaluation_source")
    if not isinstance(catalogs_value, list) or not isinstance(evaluation_source, str):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")
    catalogs = [item for item in catalogs_value if isinstance(item, dict)]
    if len(catalogs) != len(catalogs_value):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")

    version = (
        request.path_parameters.get("benchmark_version")
        if request.operation is WorkflowOperation.MCSB_DETAIL
        else request.query.get("version", "v1")
    )
    selected_catalog = next(
        (
            item
            for item in catalogs
            if isinstance(item.get("benchmark"), dict)
            and item["benchmark"].get("benchmark_version") == version
        ),
        None,
    )
    if selected_catalog is None:
        raise HTTPException(status_code=404, detail=f"unknown MCSB version {version!r}")
    controls_value = selected_catalog.get("controls")
    if not isinstance(controls_value, list) or not all(
        isinstance(item, dict) for item in controls_value
    ):
        raise HTTPException(status_code=503, detail="authoritative MCSB catalog is malformed")
    controls = cast(list[dict[str, object]], controls_value)

    if request.operation is WorkflowOperation.MCSB_DETAIL:
        control_id = request.path_parameters.get("control_id", "")
        selected = next((item for item in controls if item.get("control_id") == control_id), None)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"unknown MCSB control {control_id!r}")
        return dict(selected)

    domain = request.query.get("domain", "").strip().lower()
    coverage = request.query.get("coverage", "").strip().lower()
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if (not domain or str(item.get("domain", "")).lower() == domain)
        and (not coverage or str(item.get("coverage", "")).lower() == coverage)
        and (
            not needle or needle in f"{item.get('control_id', '')}\n{item.get('title', '')}".lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "benchmark": selected_catalog["benchmark"],
        "versions": [
            item["benchmark"] for item in catalogs if isinstance(item.get("benchmark"), dict)
        ],
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "facets": {
            "by_domain": _rule_counts(controls, "domain"),
            "by_coverage": _rule_counts(controls, "coverage"),
        },
        "controls": [
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "benchmark_version",
                    "rule_ids",
                    "runtime_observation_ids",
                    "manual_evidence_refs",
                    "source",
                    "evaluation_source",
                }
            }
            for item in matched[offset : offset + limit]
        ],
        "evaluation_source": evaluation_source,
    }


def _wara_catalog_payload(
    stored: Mapping[str, object],
    request: WorkflowReadRequest,
) -> dict[str, object]:
    controls_value = stored.get("controls")
    inventory_value = stored.get("inventory")
    evaluation_source = stored.get("evaluation_source")
    if (
        not isinstance(controls_value, list)
        or not isinstance(inventory_value, dict)
        or not isinstance(evaluation_source, str)
    ):
        raise HTTPException(status_code=503, detail="authoritative WARA catalog is malformed")
    controls = [item for item in controls_value if isinstance(item, dict)]
    if len(controls) != len(controls_value):
        raise HTTPException(status_code=503, detail="authoritative WARA catalog is malformed")

    if request.operation is WorkflowOperation.WARA_DETAIL:
        recommendation_id = request.path_parameters.get("recommendation_id", "")
        selected = next((item for item in controls if item.get("id") == recommendation_id), None)
        if selected is None:
            raise HTTPException(
                status_code=404,
                detail=f"unknown WARA recommendation {recommendation_id!r}",
            )
        return dict(selected)

    filter_fields = (
        "resource_type",
        "recommendation_control",
        "impact",
        "lifecycle",
        "product_group_verified",
        "automation_available",
        "mapping_disposition",
        "applicability",
        "evaluation_status",
        "satisfaction",
    )
    filters = {field: request.query.get(field, "").strip().lower() for field in filter_fields}
    needle = request.query.get("q", "").strip().lower()
    matched = [
        item
        for item in controls
        if all(
            not expected or str(item.get(field, "")).lower() == expected
            for field, expected in filters.items()
        )
        and (
            not needle
            or needle
            in "\n".join(
                str(item.get(field, ""))
                for field in ("id", "title", "resource_type", "recommendation_control")
            ).lower()
        )
    ]
    offset = request.offset or 0
    limit = request.limit or 100
    return {
        "total": len(controls),
        "filtered_total": len(matched),
        "offset": offset,
        "limit": limit,
        "facets": {
            "by_resource_type": _wara_counts(controls, "resource_type"),
            "by_recommendation_control": _wara_counts(
                controls,
                "recommendation_control",
            ),
            "by_impact": _wara_counts(controls, "impact"),
            "by_lifecycle": _wara_counts(controls, "lifecycle"),
            "by_product_group_verified": _wara_counts(
                controls,
                "product_group_verified",
            ),
            "by_automation_available": _wara_counts(
                controls,
                "automation_available",
            ),
            "by_mapping_disposition": _wara_counts(
                controls,
                "mapping_disposition",
            ),
            "by_applicability": _wara_counts(controls, "applicability"),
            "by_evaluation": _wara_counts(controls, "evaluation_status"),
            "by_satisfaction": _wara_counts(controls, "satisfaction"),
        },
        "controls": matched[offset : offset + limit],
        "inventory": dict(inventory_value),
        "evaluation_source": evaluation_source,
        "source_revision": stored.get("source_revision"),
        "crosswalk_digest": stored.get("crosswalk_digest"),
    }


class UnavailableWorkflowAdapters:
    """Fail every workflow route closed while preserving route registration."""

    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        del request
        raise HTTPException(status_code=503, detail="authoritative workflow store is unavailable")

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="workflow proposal outbox is unavailable")


@dataclass(frozen=True, slots=True)
class PostgresOperationsAdapters:
    """Serve operations projections, proposals, replay, and signed webhook intake."""

    store: PostgresFamilyStore
    webhook_secret: str | None = None
    read_investigation_replay: PostgresReadInvestigationReplayStore | None = None
    context_selection_registry: ContextSelectionRegistry | None = None

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        """Read one explicitly materialized operations projection."""
        if query.operation in {
            "blast_radius.simulate",
            "ontology.instance.explore",
            "ontology.instance.list",
        }:
            try:
                ontology_projection = await self.store.read_projection(
                    family="operations",
                    operation="ontology.graph",
                )
                if query.operation == "ontology.instance.explore":
                    return await project_inventory_instance(
                        query=query,
                        reader=self.store,
                        ontology_projection=ontology_projection,
                        selection_registry=self.context_selection_registry,
                    )
                if query.operation == "ontology.instance.list":
                    return await project_inventory_instances(
                        query=query,
                        reader=self.store,
                        ontology_projection=ontology_projection,
                        selection_registry=self.context_selection_registry,
                    )
                return await project_inventory_impact(
                    query=query,
                    reader=self.store,
                    ontology_projection=ontology_projection,
                )
            except PostgresFamilyStoreUnavailable as exc:
                raise ProjectionUnavailableError from exc
        operation = query.operation
        if operation in {"ontology.declaration.detail", "ontology.declaration.dependents"}:
            operation = (
                f"ontology.declaration.detail.{_highest_operator_role(query.roles).value.lower()}"
            )
        try:
            payload = await self.store.read_projection(
                family="operations",
                operation=operation,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc
        if query.operation == "ontology.declaration.detail":
            return _ontology_declaration_projection(payload, query, section="details")
        if query.operation == "ontology.declaration.dependents":
            return _ontology_declaration_projection(payload, query, section="dependents")
        if query.operation == "ontology.release.diff":
            return _ontology_release_diff(payload, query)
        if query.operation == "ontology.evidence.health":
            return _ontology_evidence_health(payload, query)
        return payload

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        """Persist one event proposal without publishing or executing it."""
        try:
            stored = await self.store.append_proposal(
                family="operations",
                operation=proposal.operation,
                principal_id=proposal.principal_id,
                idempotency_key=proposal.idempotency_key,
                payload=_mapping(asdict(proposal)),
            )
        except PostgresProposalConflict as exc:
            raise ProposalConflictError from exc
        except PostgresFamilyStoreUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ProposalReceipt(
            request_id=stored.proposal_id,
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at=stored.accepted_at,
        )

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        """Replay authoritative audit events using the durable sequence watermark."""

        if query.stream.startswith("read-investigation:"):
            if self.read_investigation_replay is None:
                raise ProjectionUnavailableError
            return await self.read_investigation_replay.replay(query)
        try:
            stored = await self.store.replay(
                stream=query.stream,
                principal_id=query.principal_id,
                after_sequence=query.after_sequence,
                limit=query.limit,
            )
        except PostgresFamilyStoreUnavailable as exc:
            raise ProjectionUnavailableError from exc
        events = tuple(ReplayEvent(record.sequence, record.event, record.data) for record in stored)
        watermark = events[-1].sequence if events else query.after_sequence or 0
        return ReplayBatch(events=events, watermark=watermark)

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        """Verify an HMAC signature before accepting webhook proposals."""
        del operation
        if self.webhook_secret is None:
            raise HTTPException(status_code=503, detail="webhook signing input is unavailable")
        supplied = headers.get("x-fdai-signature", "")
        if not supplied.startswith("sha256="):
            return False
        expected = hmac.new(self.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, supplied[len("sha256=") :])


class UnavailableOperationsAdapters:
    """Fail all operations dependencies closed while keeping their routes visible."""

    async def read(self, query: ProjectionQuery) -> Mapping[str, object]:
        del query
        raise ProjectionUnavailableError

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        del proposal
        raise HTTPException(status_code=503, detail="event proposal outbox is unavailable")

    async def replay(self, query: ReplayQuery) -> ReplayBatch:
        del query
        raise ProjectionUnavailableError

    async def verify(
        self,
        operation: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> bool:
        del operation, headers, body
        raise HTTPException(status_code=503, detail="webhook signing input is unavailable")


_OPERATOR_ROLE_RANK = {
    OperatorRole.READER: 0,
    OperatorRole.CONTRIBUTOR: 1,
    OperatorRole.APPROVER: 2,
    OperatorRole.OWNER: 3,
}


def _highest_operator_role(roles: frozenset[OperatorRole]) -> OperatorRole:
    ordinary_roles = roles & _OPERATOR_ROLE_RANK.keys()
    if not ordinary_roles:
        raise ProjectionUnavailableError("ordinary Operator role is unavailable")
    return max(ordinary_roles, key=_OPERATOR_ROLE_RANK.__getitem__)


def _ontology_declaration_projection(
    payload: Mapping[str, object],
    query: ProjectionQuery,
    *,
    section: str,
) -> Mapping[str, object]:
    if payload.get("purpose") != query.purpose or payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology declaration projection boundary is invalid")
    details = payload.get(section)
    if not isinstance(details, Mapping):
        raise ProjectionUnavailableError("ontology declaration projection is malformed")
    kind = query.path.get("kind", "")
    declarations = details.get(kind)
    if not isinstance(declarations, Mapping):
        raise ProjectionNotFoundError(kind)
    declaration = declarations.get(query.path.get("name", ""))
    if not isinstance(declaration, Mapping):
        raise ProjectionNotFoundError(query.path.get("name", ""))
    return declaration


def _ontology_release_diff(
    payload: Mapping[str, object],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    if payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology release diff boundary is invalid")
    candidate = query.path.get("candidate_digest", "")
    if re.fullmatch(r"sha256:[a-f0-9]{64}", candidate) is None:
        raise ValueError("candidate ontology release digest MUST be sha256")
    release_digests = payload.get("release_digests")
    diffs = payload.get("diffs")
    if not isinstance(release_digests, list) or not isinstance(diffs, Mapping):
        raise ProjectionUnavailableError("ontology release diff registry is malformed")
    requested_base = query.params.get("base", (None,))[-1]
    if requested_base is None:
        try:
            candidate_index = release_digests.index(candidate)
        except ValueError as exc:
            raise ProjectionNotFoundError(candidate) from exc
        if candidate_index == 0:
            raise ProjectionNotFoundError("previous ontology release")
        base = release_digests[candidate_index - 1]
    else:
        base = requested_base
    if not isinstance(base, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", base) is None:
        raise ValueError("base ontology release digest MUST be sha256")
    diff = diffs.get(f"{candidate}|{base}")
    if not isinstance(diff, Mapping):
        raise ProjectionNotFoundError(f"{candidate}|{base}")
    return {
        **diff,
        "registry_truncated": payload.get("truncated") is True,
        "registry_truncation_reason": payload.get("truncation_reason"),
    }


def _ontology_evidence_health(
    payload: Mapping[str, object],
    query: ProjectionQuery,
) -> Mapping[str, object]:
    if payload.get("mutation_authority") is not False:
        raise ProjectionUnavailableError("ontology evidence health boundary is invalid")
    health = payload.get("evidence_health")
    if not isinstance(health, Mapping):
        raise ProjectionUnavailableError("ontology evidence health registry is malformed")
    name = query.path.get("name", "")
    projection = health.get(name)
    if not isinstance(projection, Mapping):
        raise ProjectionNotFoundError(name)
    return projection


def _mapping(value: object) -> Mapping[str, object]:
    normalized = json.loads(json.dumps(value, default=str))
    if not isinstance(normalized, dict):
        raise ValueError("proposal payload MUST serialize to a JSON object")
    return cast(Mapping[str, object], normalized)


__all__ = [
    "PostgresConversationAdapters",
    "PostgresOperationsAdapters",
    "PostgresWorkflowAdapters",
    "UnavailableConversationAdapters",
    "UnavailableOperationsAdapters",
    "UnavailableWorkflowAdapters",
]
