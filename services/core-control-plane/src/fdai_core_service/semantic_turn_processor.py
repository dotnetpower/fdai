"""Decode and project one bounded Operator semantic turn."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    CausalEvidenceJoin,
    MetricWindow,
    QueryPlanExecution,
    TopologyDiff,
    TopologyGraphAt,
)
from fdai.core.ontology_platform.query_values import QueryTable
from fdai_service_contracts import (
    OperatorRole,
    RuleSearchProjection,
    RuleSearchRequest,
    SemanticRoute,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticUnavailableReason,
    rule_search_query_digest,
)
from fdai_service_contracts import (
    SemanticTurnResult as ContractSemanticTurnResult,
)
from fdai_service_contracts.ontology_query import TaskStatus, content_digest

from .contract_codecs import (
    OPERATOR_PROJECTION_PRODUCER_V12,
    OPERATOR_REQUEST_CONSUMER_V13,
)
from .semantic_relationship_projection import (
    project_ontology_relationships,
    render_ontology_relationship_answer,
)

_PROJECTION_NAMESPACE = UUID("00000000-0000-0000-0000-000000000000")
_MAX_REQUEST_LIFETIME_SECONDS = 90.0
_ROLE_ORDER = (
    OperatorRole.READER,
    OperatorRole.CONTRIBUTOR,
    OperatorRole.APPROVER,
    OperatorRole.OWNER,
)
_ROLE_MAP = {
    OperatorRole.READER: Role.READER,
    OperatorRole.CONTRIBUTOR: Role.CONTRIBUTOR,
    OperatorRole.APPROVER: Role.APPROVER,
    OperatorRole.OWNER: Role.OWNER,
}
_ROUTE_BY_DISPOSITION: dict[str, SemanticRoute] = {
    "clarification": "semantic_clarification",
    "unsupported": "semantic_unsupported",
    "action_draft": "semantic_action_draft",
    "cancelled": "semantic_cancellation",
}
_AUTHORITATIVE_EVIDENCE_UNAVAILABLE_REASONS = {
    "semantic_evidence_held",
    "semantic_evidence_incomplete",
}


@dataclass(frozen=True, slots=True)
class _SemanticProjectionExtensions:
    rule_search: RuleSearchProjection | None = None
    technical_details: dict[str, object] | None = None


class SemanticTurnRejectedError(ValueError):
    """Reject one malformed or unauthorized semantic request before runtime I/O."""


class SemanticTurnRuntime(Protocol):
    """Subset of ``SemanticConversationRuntime`` required by the event processor."""

    async def handle(
        self,
        *,
        utterance: str,
        prior_turns: tuple[Turn, ...],
        principal: Principal,
        cancelled: asyncio.Event | None = None,
    ) -> RuntimeSemanticTurnResult: ...


class SemanticTurnResultStore(Protocol):
    """Atomically retain the canonical projection for one idempotency key."""

    async def get(self, idempotency_key: str) -> bytes | None: ...

    async def claim(self, idempotency_key: str, request_digest: str) -> str | None: ...

    async def release(
        self,
        idempotency_key: str,
        request_digest: str,
        claim_id: str,
    ) -> bool: ...

    async def put_if_absent(self, idempotency_key: str, projection: bytes) -> bool: ...


class SemanticTurnProcessor:
    """Validate, execute, evidence-gate, and idempotently project semantic turns.

    The injected runtime may be unavailable. In that state every valid request
    terminates as a schema-valid hold without fabricating model or provider evidence.
    """

    def __init__(
        self,
        *,
        runtime: SemanticTurnRuntime | None,
        results: SemanticTurnResultStore,
        purpose: str = "operations-review",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not purpose:
            raise ValueError("semantic turn purpose MUST be non-empty")
        self._runtime = runtime
        self._results = results
        self._purpose = purpose
        self._now = now or (lambda: datetime.now(UTC))

    async def process(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: asyncio.Event | None = None,
    ) -> bytes:
        """Return one canonical v1.2 projection or reject invalid boundary input."""

        envelope, request, requested_at = _decode_request(payload)
        principal = _principal(request)
        if request.purpose != self._purpose:
            raise SemanticTurnRejectedError("semantic_purpose_not_allowed")

        idempotency_key = str(envelope["idempotency_key"])
        request_digest = _request_digest(envelope, request)
        if request.cancelled or (cancelled is not None and cancelled.is_set()):
            return self._held_projection(
                envelope,
                request,
                request_digest=request_digest,
                reason_code="semantic_request_cancelled",
                disposition="cancelled",
            )
        now = _aware_utc(self._now(), field="semantic processor clock")
        deadline = _aware_utc(request.deadline_at, field="semantic deadline_at")
        remaining = (deadline - now).total_seconds()
        if remaining > _MAX_REQUEST_LIFETIME_SECONDS:
            raise SemanticTurnRejectedError("semantic_deadline_too_far")
        if remaining <= 0:
            return self._held_projection(
                envelope,
                request,
                request_digest=request_digest,
                reason_code="semantic_deadline_exceeded",
            )

        operation_task = asyncio.create_task(
            self._process_idempotent(
                envelope=envelope,
                request=request,
                requested_at=requested_at,
                principal=principal,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                cancelled=cancelled,
            )
        )
        cancellation_task = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        waiters: set[asyncio.Task[object]] = {operation_task}
        if cancellation_task is not None:
            waiters.add(cancellation_task)
        try:
            done, pending = await asyncio.wait(
                waiters,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task is not None and cancellation_task in done:
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_request_cancelled",
                    disposition="cancelled",
                )
            if operation_task not in done:
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_deadline_exceeded",
                )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            return operation_task.result()
        except asyncio.CancelledError:
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise
        finally:
            if cancellation_task is not None and not cancellation_task.done():
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)

    async def _process_idempotent(
        self,
        *,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        requested_at: datetime,
        principal: Principal,
        idempotency_key: str,
        request_digest: str,
        cancelled: asyncio.Event | None,
    ) -> bytes:
        try:
            prior = await self._results.get(idempotency_key)
        except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
            return self._held_projection(
                envelope,
                request,
                request_digest=request_digest,
                reason_code="semantic_result_store_unavailable",
            )
        if prior is not None:
            try:
                return _canonical_projection(prior, request_digest=request_digest)
            except SemanticTurnRejectedError:
                raise
            except Exception:  # noqa: BLE001 - corrupt persistence fails closed
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )

        try:
            claim_id = await self._results.claim(idempotency_key, request_digest)
        except SemanticTurnRejectedError:
            raise
        except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
            return self._held_projection(
                envelope,
                request,
                request_digest=request_digest,
                reason_code="semantic_result_store_unavailable",
            )
        if claim_id is None:
            return await self._wait_for_claimed_projection(
                envelope=envelope,
                request=request,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )

        claim_finalized = False
        try:
            try:
                result, extensions = await self._execute(
                    request=request,
                    requested_at=requested_at,
                    principal=principal,
                    cancelled=cancelled,
                )
                projection = self._projection(
                    envelope,
                    request,
                    result,
                    extensions=extensions,
                    request_digest=request_digest,
                )
                created = await self._results.put_if_absent(idempotency_key, projection)
                if created:
                    claim_finalized = True
                    return projection
                winner = await self._results.get(idempotency_key)
            except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )
            if winner is None:
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )
            try:
                canonical = _canonical_projection(winner, request_digest=request_digest)
                claim_finalized = True
                return canonical
            except SemanticTurnRejectedError:
                raise
            except Exception:  # noqa: BLE001 - corrupt persistence fails closed
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )
        finally:
            if not claim_finalized:
                await _release_claim(
                    self._results,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    claim_id=claim_id,
                )

    async def _wait_for_claimed_projection(
        self,
        *,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        idempotency_key: str,
        request_digest: str,
    ) -> bytes:
        delay = 0.01
        while True:
            await asyncio.sleep(delay)
            try:
                winner = await self._results.get(idempotency_key)
            except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )
            if winner is None:
                delay = min(delay * 2, 0.25)
                continue
            try:
                return _canonical_projection(winner, request_digest=request_digest)
            except SemanticTurnRejectedError:
                raise
            except Exception:  # noqa: BLE001 - corrupt persistence fails closed
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )

    async def _execute(
        self,
        *,
        request: SemanticTurnRequest,
        requested_at: datetime,
        principal: Principal,
        cancelled: asyncio.Event | None,
    ) -> tuple[ContractSemanticTurnResult, _SemanticProjectionExtensions | None]:
        if request.cancelled or (cancelled is not None and cancelled.is_set()):
            return _terminal_result(request, "cancelled", "semantic_request_cancelled"), None
        now = _aware_utc(self._now(), field="semantic processor clock")
        deadline = _aware_utc(request.deadline_at, field="semantic deadline_at")
        remaining = (deadline - now).total_seconds()
        if remaining <= 0:
            return _terminal_result(request, "held", "semantic_deadline_exceeded"), None
        if self._runtime is None:
            return _terminal_result(request, "held", "semantic_runtime_unavailable"), None

        runtime_cancelled = asyncio.Event()
        runtime_task = asyncio.create_task(
            self._runtime.handle(
                utterance=request.utterance,
                prior_turns=_prior_turns(request, requested_at=requested_at),
                principal=principal,
                cancelled=runtime_cancelled,
            )
        )
        cancellation_task = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        waiters: set[asyncio.Task[object]] = {runtime_task}
        if cancellation_task is not None:
            waiters.add(cancellation_task)
        try:
            done, pending = await asyncio.wait(
                waiters,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_task is not None and cancellation_task in done:
                runtime_cancelled.set()
                runtime_task.cancel()
                await asyncio.gather(runtime_task, return_exceptions=True)
                return _terminal_result(request, "cancelled", "semantic_request_cancelled"), None
            if runtime_task not in done:
                runtime_cancelled.set()
                runtime_task.cancel()
                await asyncio.gather(runtime_task, return_exceptions=True)
                return _terminal_result(request, "held", "semantic_deadline_exceeded"), None
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            runtime_result = runtime_task.result()
            return _project_runtime_result(request, runtime_result)
        except asyncio.CancelledError:
            runtime_cancelled.set()
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
            raise
        except Exception:  # noqa: BLE001 - runtime/provider detail must not cross the wire
            return _terminal_result(request, "held", "semantic_runtime_failed"), None
        finally:
            if cancellation_task is not None and not cancellation_task.done():
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)

    def _projection(
        self,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        result: ContractSemanticTurnResult,
        *,
        extensions: _SemanticProjectionExtensions | None,
        request_digest: str,
    ) -> bytes:
        semantic_result = result.model_dump(mode="json", exclude_none=True)
        evidence_digest = content_digest(semantic_result)
        projection_id = str(
            uuid5(
                _PROJECTION_NAMESPACE,
                f"{envelope['request_id']}\0{evidence_digest}",
            )
        )
        payload: dict[str, object] = {
            "request_kind": "semantic_query",
            "request_digest": request_digest,
        }
        if extensions is not None:
            if extensions.rule_search is not None:
                payload["rule_search"] = extensions.rule_search.model_dump(mode="json")
            if extensions.technical_details is not None:
                payload["technical_details"] = extensions.technical_details
        projection = {
            "schema_version": "1.2.0",
            "projection_id": projection_id,
            "request_id": envelope["request_id"],
            "correlation_id": envelope["correlation_id"],
            "idempotency_key": envelope["idempotency_key"],
            "status": result.disposition.value,
            "recorded_at": _aware_utc(self._now(), field="semantic processor clock").isoformat(),
            "payload": payload,
            "evidence_digest": evidence_digest,
            "semantic_result": semantic_result,
        }
        return OPERATOR_PROJECTION_PRODUCER_V12.encode(projection)

    def _held_projection(
        self,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        *,
        request_digest: str,
        reason_code: str,
        disposition: str = "held",
    ) -> bytes:
        return self._projection(
            envelope,
            request,
            _terminal_result(request, disposition, reason_code),
            extensions=None,
            request_digest=request_digest,
        )


def _decode_request(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], SemanticTurnRequest, datetime]:
    try:
        envelope = OPERATOR_REQUEST_CONSUMER_V13.decode_mapping(payload)
        if envelope.get("request_kind") != "semantic_query":
            raise SemanticTurnRejectedError("semantic_request_kind_required")
        semantic_turn = envelope.get("semantic_turn")
        if not isinstance(semantic_turn, dict):
            raise SemanticTurnRejectedError("semantic_turn_required")
        request = SemanticTurnRequest.model_validate(semantic_turn)
        requested_at_raw = envelope["requested_at"]
        if not isinstance(requested_at_raw, str):
            raise SemanticTurnRejectedError("semantic_requested_at_invalid")
        requested_at = _aware_utc(
            datetime.fromisoformat(requested_at_raw.replace("Z", "+00:00")),
            field="semantic requested_at",
        )
        _aware_utc(request.deadline_at, field="semantic deadline_at")
        return envelope, request, requested_at
    except SemanticTurnRejectedError:
        raise
    except Exception as exc:
        raise SemanticTurnRejectedError("semantic_request_invalid") from exc


def _principal(request: SemanticTurnRequest) -> Principal:
    ordinary_roles = [role for role in _ROLE_ORDER if role in request.principal.roles]
    if not ordinary_roles:
        raise SemanticTurnRejectedError("semantic_break_glass_only")
    selected = ordinary_roles[-1]
    return Principal(id=request.principal.subject_id, role=_ROLE_MAP[selected])


def _prior_turns(
    request: SemanticTurnRequest,
    *,
    requested_at: datetime,
) -> tuple[Turn, ...]:
    turns = [
        Turn(
            turn_id=f"{request.turn_id}:prior:{index}",
            direction="inbound" if item.role == "user" else "outbound",
            content=item.content,
            timestamp=requested_at,
        )
        for index, item in enumerate(request.prior_turns)
    ]
    anchor = _bound_context_turn(request, requested_at=requested_at)
    if anchor is not None:
        # Kept last so the planner's bounded context window never drops the binding.
        turns.append(anchor)
    return tuple(turns)


def _bound_context_turn(
    request: SemanticTurnRequest,
    *,
    requested_at: datetime,
) -> Turn | None:
    binding = request.bound_context
    if binding is None:
        return None
    fields = [f"kind={binding.kind}"]
    if binding.incident_id is not None:
        fields.append(f"incident_id={binding.incident_id}")
    if binding.correlation_id is not None:
        fields.append(f"correlation_id={binding.correlation_id}")
    return Turn(
        turn_id=f"{request.turn_id}:bound-context",
        direction="system",
        content="Bound conversation context: " + ", ".join(fields),
        timestamp=requested_at,
    )


def _project_runtime_result(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
) -> tuple[ContractSemanticTurnResult, _SemanticProjectionExtensions | None]:
    if result.disposition != "answered":
        reason_codes = {
            "clarification": "semantic_clarification_required",
            "held": "semantic_evidence_held",
            "unsupported": "semantic_request_unsupported",
            "action_draft": "semantic_action_draft",
            "cancelled": "semantic_request_cancelled",
        }
        reason_code = reason_codes.get(result.disposition, "semantic_runtime_failed")
        disposition = result.disposition if result.disposition in reason_codes else "held"
        answer = result.planning.clarification if result.disposition == "clarification" else None
        return _terminal_result(request, disposition, reason_code, answer=answer), None

    planning = result.planning
    plan = planning.plan
    execution = result.execution
    if (
        plan is None
        or execution is None
        or result.intent_graph is None
        or result.intent_graph_evidence is None
        or planning.manifest_digest is None
        or planning.manifest_digest != plan.semantic_catalog_digest
        or execution.plan_digest != plan.plan_digest
        or execution.status != "completed"
        or not execution.receipts
        or any(receipt.status is not TaskStatus.COMPLETED for receipt in execution.receipts)
        or not _projected_answer_evidence_is_complete(result, execution)
    ):
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref for receipt in execution.receipts for evidence_ref in receipt.evidence_refs
        )
    )
    if not evidence_refs or len(evidence_refs) > 12:
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    execution_receipt_digest = content_digest(
        {
            "plan_digest": execution.plan_digest,
            "status": execution.status,
            "output_node_ids": execution.output_node_ids,
            "receipts": [receipt.model_dump(mode="json") for receipt in execution.receipts],
        }
    )
    checks_total = len(execution.receipts)
    rule_search_found, rule_search, rule_search_node_id = _project_rule_search(result, execution)
    if rule_search_found and rule_search is None:
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    incident_found, incident_evidence, incident_node_id = _project_incident_evidence(
        result,
        execution,
    )
    if incident_found and incident_evidence is None:
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    relationships_found, relationships, relationships_node_id = project_ontology_relationships(
        result,
        execution,
    )
    if relationships_found and relationships is None:
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    answer, technical_details = _render_query_answer(
        request,
        execution,
        rule_search=rule_search,
        rule_search_node_id=rule_search_node_id,
        incident_evidence=incident_evidence,
        incident_node_id=incident_node_id,
        ontology_relationships=relationships,
        ontology_relationships_node_id=relationships_node_id,
    )
    if answer is None or technical_details is None:
        return _terminal_result(request, "held", "semantic_evidence_incomplete"), None
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code="semantic_answer_verified",
        semantic_route="verified_query_plan",
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
        ontology_release_digest=plan.ontology_release_digest,
        principal_manifest_digest=planning.manifest_digest,
        plan_digest=plan.plan_digest,
        execution_receipt_digest=execution_receipt_digest,
        intent_graph=result.intent_graph,
        intent_graph_evidence=result.intent_graph_evidence,
        evidence_refs=evidence_refs,
        checks_completed=checks_total,
        checks_total=checks_total,
        answer=answer,
    ), _SemanticProjectionExtensions(
        rule_search=rule_search,
        technical_details=technical_details,
    )


def _project_rule_search(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, RuleSearchProjection | None, str | None]:
    plan = result.planning.plan
    if plan is None:
        return True, None, None
    nodes = getattr(plan, "nodes", ())
    catalog_nodes = []
    for node in nodes:
        if getattr(node, "node_id", None) not in execution.output_node_ids:
            continue
        try:
            arguments = node.arguments
        except Exception:  # noqa: BLE001, S112 - malformed plan output fails closed
            continue
        if isinstance(arguments, dict) and arguments.get("function_name") == "catalog.search_rules":
            catalog_nodes.append((node, arguments))
    if not catalog_nodes:
        return False, None, None
    if len(catalog_nodes) != 1:
        return True, None, None
    node, node_arguments = catalog_nodes[0]
    node_id = getattr(node, "node_id", None)
    query_arguments = node_arguments.get("arguments")
    node_result = execution.results.get(node_id) if isinstance(node_id, str) else None
    node_kind = getattr(getattr(node, "kind", None), "value", None)
    receipts = tuple(
        receipt for receipt in execution.receipts if receipt.task_id == f"query:{node_id}"
    )
    if (
        not isinstance(node_id, str)
        or not isinstance(query_arguments, dict)
        or node_result is None
        or node_kind != "function"
        or len(receipts) != 1
        or receipts[0].goal_id != node_id
        or receipts[0].intent != "function"
        or receipts[0].capability != "query.function"
        or receipts[0].evidence_refs != node_result.evidence_refs
    ):
        return True, None, None
    value = node_result.value
    if not isinstance(value, dict):
        return True, None, None
    try:
        query_request = RuleSearchRequest.model_validate(query_arguments)
        query_digest = rule_search_query_digest(query_request)
        function_invocation_receipt = receipts[0]
        projection = RuleSearchProjection.model_validate(
            {
                "query_digest": query_digest,
                "retrieval_receipt_digest": value.get("retrieval_receipt_digest"),
                "function_invocation_receipt_digest": content_digest(
                    function_invocation_receipt.model_dump(mode="json")
                ),
                "candidates": value.get("candidates"),
                "retrieval_receipt": value.get("retrieval_receipt"),
                "function_invocation_receipt": function_invocation_receipt,
                "authority": value.get("authority"),
                "execution_authority": value.get("execution_authority"),
            }
        )
    except Exception:  # noqa: BLE001 - untrusted function output fails closed
        return True, None, None
    if (
        projection.retrieval_receipt.operation != query_request.operation
        or projection.retrieval_receipt.corpus != query_request.corpus
        or len(projection.candidates) > query_request.limit
        or projection.retrieval_receipt.catalog_digest != plan.semantic_catalog_digest
    ):
        return True, None, None
    return True, projection, node_id


def _project_incident_evidence(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, dict[str, object] | None, str | None]:
    plan = result.planning.plan
    if plan is None:
        return True, None, None
    incident_nodes: list[tuple[object, dict[str, Any]]] = []
    for node in getattr(plan, "nodes", ()):
        if getattr(node, "node_id", None) not in execution.output_node_ids:
            continue
        try:
            arguments = node.arguments
        except Exception:  # noqa: BLE001, S112 - malformed plan output fails closed
            continue
        if isinstance(arguments, dict) and arguments.get("function_name") == (
            "query.incident_evidence"
        ):
            incident_nodes.append((node, arguments))
    if not incident_nodes:
        return False, None, None
    if len(incident_nodes) != 1:
        return True, None, None
    node, node_arguments = incident_nodes[0]
    node_id = getattr(node, "node_id", None)
    query_arguments = node_arguments.get("arguments")
    node_result = execution.results.get(node_id) if isinstance(node_id, str) else None
    node_kind = getattr(getattr(node, "kind", None), "value", None)
    receipts = tuple(
        receipt for receipt in execution.receipts if receipt.task_id == f"query:{node_id}"
    )
    if (
        not isinstance(node_id, str)
        or not isinstance(query_arguments, dict)
        or node_result is None
        or node_kind != "function"
        or len(receipts) != 1
        or receipts[0].goal_id != node_id
        or receipts[0].intent != "function"
        or receipts[0].capability != "query.function"
        or receipts[0].evidence_refs != node_result.evidence_refs
    ):
        return True, None, None
    value = node_result.value
    incident_id = query_arguments.get("incident_id")
    correlation_id = query_arguments.get("correlation_id")
    limit = query_arguments.get("limit")
    if (
        not isinstance(value, dict)
        or not isinstance(incident_id, str)
        or not isinstance(correlation_id, str)
        or not correlation_id
        or not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 500
        or value.get("incident_id") != incident_id
        or value.get("correlation_id") != correlation_id
        or value.get("authority") != "audit_projection"
        or value.get("cause_claim_supported") is not False
        or value.get("execution_authority") is not False
        or _contains_key(value, "cause")
    ):
        return True, None, None
    profile = value.get("incident_profile")
    evidence = value.get("correlated_evidence")
    gaps = value.get("evidence_gaps")
    evidence_refs = value.get("evidence_refs")
    truncated = value.get("truncated")
    if (
        (profile is not None and not isinstance(profile, dict))
        or not isinstance(evidence, list)
        or len(evidence) > limit
        or not isinstance(gaps, list)
        or not isinstance(evidence_refs, list)
        or not isinstance(truncated, bool)
        or any(not isinstance(item, dict) for item in evidence)
        or any(not isinstance(item, str) for item in gaps)
        or any(not isinstance(item, str) for item in evidence_refs)
    ):
        return True, None, None
    if profile is not None and (
        profile.get("incident_id") != incident_id or profile.get("correlation_id") != correlation_id
    ):
        return True, None, None
    audit_refs = [item.get("audit_ref") for item in evidence]
    if any(not isinstance(item, str) for item in audit_refs) or audit_refs != evidence_refs:
        return True, None, None
    if truncated and "correlated_audit_truncated" not in gaps:
        return True, None, None
    return True, value, node_id


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_key(item, key) for item in value)
    return False


def _projected_answer_evidence_is_complete(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> bool:
    graph = result.intent_graph
    evidence = result.intent_graph_evidence
    if not isinstance(graph, dict) or not isinstance(evidence, dict):
        return False
    graph_goals = graph.get("goals")
    evidence_goals = evidence.get("goals")
    if (
        graph.get("schema_version") != 2
        or graph.get("action_posture") != "advise_only"
        or evidence.get("schema_version") != 1
        or evidence.get("status") != "completed"
        or evidence.get("evidence_mode") != "operational_grounded"
        or not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not 1 <= len(graph_goals) <= 8
        or len(graph_goals) != len(evidence_goals)
        or len(evidence_goals) != len(execution.receipts)
    ):
        return False

    projected_refs: list[str] = []
    executed_refs: list[str] = []
    for graph_goal, evidence_goal, receipt in zip(
        graph_goals,
        evidence_goals,
        execution.receipts,
        strict=True,
    ):
        if not isinstance(graph_goal, dict) or not isinstance(evidence_goal, dict):
            return False
        goal_id = graph_goal.get("goal_id")
        evidence_refs = evidence_goal.get("evidence_refs", [])
        if (
            not isinstance(goal_id, str)
            or evidence_goal.get("goal_id") != goal_id
            or evidence_goal.get("intent") != graph_goal.get("intent")
            or evidence_goal.get("capability") != graph_goal.get("capability")
            or evidence_goal.get("task_id") != receipt.task_id
            or evidence_goal.get("status") != "completed"
            or not isinstance(evidence_refs, list)
            or any(not isinstance(item, str) for item in evidence_refs)
            or tuple(evidence_refs) != receipt.evidence_refs
        ):
            return False
        projected_refs.extend(evidence_refs)
        executed_refs.extend(receipt.evidence_refs)
    return tuple(dict.fromkeys(projected_refs)) == tuple(dict.fromkeys(executed_refs))


def _terminal_result(
    request: SemanticTurnRequest,
    disposition: str,
    reason_code: str,
    *,
    answer: str | None = None,
) -> ContractSemanticTurnResult:
    semantic_route = _ROUTE_BY_DISPOSITION.get(disposition)
    unavailable_reason: SemanticUnavailableReason | None = None
    if disposition == "held":
        unavailable_reason = (
            "authoritative_evidence_unavailable"
            if reason_code in _AUTHORITATIVE_EVIDENCE_UNAVAILABLE_REASONS
            else "semantic_planner_unavailable"
        )
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition(disposition),
        reason_code=reason_code,
        semantic_route=semantic_route,
        unavailable_reason=unavailable_reason,
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
        answer=answer or _terminal_answer(request.locale, disposition, reason_code),
    )


def _render_query_answer(
    request: SemanticTurnRequest,
    execution: QueryPlanExecution,
    *,
    rule_search: RuleSearchProjection | None = None,
    rule_search_node_id: str | None = None,
    incident_evidence: dict[str, object] | None = None,
    incident_node_id: str | None = None,
    ontology_relationships: dict[str, object] | None = None,
    ontology_relationships_node_id: str | None = None,
) -> tuple[str | None, dict[str, object] | None]:
    outputs: list[dict[str, object]] = []
    projected_rule_search = False
    projected_incident = False
    projected_relationships = False
    for node_id in execution.output_node_ids:
        result = execution.results.get(node_id)
        if result is None:
            return None, None
        if isinstance(result.value, dict):
            if incident_evidence is not None and node_id == incident_node_id:
                if projected_incident:
                    return None, None
                outputs.append(
                    _incident_answer_output(
                        node_id=node_id,
                        incident_evidence=incident_evidence,
                    )
                )
                projected_incident = True
            elif ontology_relationships is not None and node_id == ontology_relationships_node_id:
                if projected_relationships:
                    return None, None
                outputs.append(
                    {
                        "node_id": node_id,
                        "ontology_relationships": ontology_relationships,
                    }
                )
                projected_relationships = True
            elif rule_search is not None and node_id == rule_search_node_id:
                if projected_rule_search:
                    return None, None
                outputs.append(
                    {
                        "node_id": node_id,
                        "rule_search": rule_search.model_dump(mode="json"),
                    }
                )
                projected_rule_search = True
            else:
                return None, None
            continue
        extension_output = _typed_extension_answer_output(node_id, result.value)
        if extension_output is not None:
            outputs.append(extension_output)
            continue
        if not isinstance(result.value, QueryTable):
            return None, None
        table = result.value
        rows: list[dict[str, object]] = []
        for row in table.rows[:20]:
            candidate_rows: list[dict[str, object]] = [
                *rows,
                {"row_id": row.row_id, "values": row.values},
            ]
            candidate = [
                *outputs,
                _answer_output(node_id=node_id, table=table, rows=candidate_rows),
            ]
            if len(_answer_json(candidate).encode("utf-8")) > 48_000:
                break
            rows = candidate_rows
        outputs.append(_answer_output(node_id=node_id, table=table, rows=rows))
    if rule_search is not None and not projected_rule_search:
        return None, None
    if incident_evidence is not None and not projected_incident:
        return None, None
    if ontology_relationships is not None and not projected_relationships:
        return None, None
    technical_details = {
        "schema_version": 1,
        "kind": "semantic_query_outputs",
        "outputs": outputs,
    }
    if len(_answer_json(outputs).encode("utf-8")) > 48_000:
        return None, None
    answer = (
        _render_incident_answer(request, outputs[0])
        if projected_incident and len(outputs) == 1
        else (
            render_ontology_relationship_answer(request.locale, outputs[0])
            if projected_relationships and len(outputs) == 1
            else _render_general_query_answer(request, outputs)
        )
    )
    return (answer, technical_details) if len(answer) <= 64_000 else (None, None)


def _incident_answer_output(
    *,
    node_id: str,
    incident_evidence: dict[str, object],
) -> dict[str, object]:
    raw_evidence = incident_evidence["correlated_evidence"]
    if not isinstance(raw_evidence, list):  # pragma: no cover - projection invariant
        raise RuntimeError("incident correlated evidence is invalid")
    displayed = raw_evidence[-20:]
    return {
        "node_id": node_id,
        "incident_profile": incident_evidence["incident_profile"],
        "correlated_evidence": displayed,
        "evidence_gaps": incident_evidence["evidence_gaps"],
        "source_truncated": incident_evidence["truncated"],
        "display_truncated": len(displayed) < len(raw_evidence),
        "causal_assessment": {
            "status": "not_available",
            "reason": "causal_analysis_not_implemented",
        },
        "next_safe_step": {
            "operation": "collect_evidence",
            "authority": "read_only",
            "execution_authority": False,
        },
    }


def _render_incident_answer(
    request: SemanticTurnRequest,
    output: Mapping[str, object],
) -> str:
    evidence = output.get("correlated_evidence")
    profile = output.get("incident_profile")
    gaps = output.get("evidence_gaps")
    evidence_count = len(evidence) if isinstance(evidence, list) else 0
    status = profile.get("status") if isinstance(profile, Mapping) else None
    status_text = status if isinstance(status, str) and status else "unknown"
    gap_values = (
        tuple(item for item in gaps if isinstance(item, str)) if isinstance(gaps, list) else ()
    )
    korean = request.locale.casefold().startswith("ko")
    if korean:
        gap_labels = {
            "impact_evidence_missing": "영향 근거",
            "grounded_citations_missing": "근거 인용",
        }
        missing = ", ".join(gap_labels.get(gap, gap) for gap in gap_values) or "없음"
        return (
            "## 검증된 인시던트 근거\n\n"
            f"- 상관관계가 있는 감사 기록 {evidence_count}건을 검증했습니다.\n"
            f"- 인시던트 상태: `{status_text}`\n\n"
            "## 제한 사항\n\n"
            "- 인과 분석이 구현되지 않아 근본 원인을 확인할 수 없습니다.\n"
            f"- 누락된 근거: {missing}\n\n"
            "## 다음 안전 단계\n\n"
            "변경을 제안하기 전에 누락된 근거를 수집하세요. "
            "이 결과는 읽기 전용이며 실행 권한을 부여하지 않습니다."
        )
    gap_labels = {
        "impact_evidence_missing": "impact evidence",
        "grounded_citations_missing": "grounded citations",
    }
    missing = ", ".join(gap_labels.get(gap, gap) for gap in gap_values) or "none"
    evidence_label = "record was" if evidence_count == 1 else "records were"
    return (
        "## Verified incident evidence\n\n"
        f"- {evidence_count} correlated audit {evidence_label} verified.\n"
        f"- Incident status: `{status_text}`\n\n"
        "## Limitations\n\n"
        "- Root cause isn't available because causal analysis hasn't been implemented.\n"
        f"- Missing evidence: {missing}\n\n"
        "## Next safe step\n\n"
        "Collect the missing evidence before proposing a change. "
        "This result is read-only and grants no execution authority."
    )


def _render_general_query_answer(
    request: SemanticTurnRequest,
    outputs: list[dict[str, object]],
) -> str:
    korean = request.locale.casefold().startswith("ko")
    lines = ["## 검증된 온톨로지 쿼리" if korean else "## Verified ontology query", ""]
    for output in outputs:
        node_id = output.get("node_id")
        rule_search = output.get("rule_search")
        if isinstance(rule_search, Mapping):
            candidates = rule_search.get("candidates")
            count = len(candidates) if isinstance(candidates, list) else 0
            lines.append(
                f"- `{node_id}`: 규칙 후보 {count}건을 검증했습니다."
                if korean
                else f"- `{node_id}`: verified {count} rule candidates."
            )
            continue
        result_kind = output.get("result_kind")
        if isinstance(result_kind, str):
            lines.append(
                f"- `{node_id}`: `{result_kind}` 결과를 검증했습니다."
                if korean
                else f"- `{node_id}`: verified a `{result_kind}` result."
            )
            continue
        returned = output.get("returned_rows")
        total = output.get("total_rows")
        lines.append(
            f"- `{node_id}`: 전체 {total}개 행 중 {returned}개를 검증했습니다."
            if korean
            else f"- `{node_id}`: verified {returned} of {total} rows."
        )
    lines.extend(
        [
            "",
            (
                "정확한 행과 증적은 기술 상세에서 확인할 수 있습니다. "
                "이 결과는 실행 권한을 부여하지 않습니다."
                if korean
                else (
                    "Exact rows and receipts are available in technical details. "
                    "This result grants no execution authority."
                )
            ),
        ]
    )
    return "\n".join(lines)


def _typed_extension_answer_output(
    node_id: str,
    value: object,
) -> dict[str, object] | None:
    if isinstance(value, TopologyGraphAt):
        return {
            "node_id": node_id,
            "result_kind": "topology.graph",
            "summary": {
                "as_of": value.as_of.isoformat(),
                "known_at": value.known_at.isoformat(),
                "object_count": len(value.graph.objects),
                "link_count": len(value.graph.links),
                "revision_count": len(value.revision_ids),
                "provider_generation_count": len(value.provider_generation_refs),
                "complete": value.complete,
                "digest": value.digest,
                "execution_authority": False,
            },
        }
    if isinstance(value, TopologyDiff):
        return {
            "node_id": node_id,
            "result_kind": "topology.diff",
            "summary": {
                "before_digest": value.before_digest,
                "after_digest": value.after_digest,
                "added_object_count": len(value.added_object_ids),
                "removed_object_count": len(value.removed_object_ids),
                "changed_object_count": len(value.changed_object_ids),
                "added_link_count": len(value.added_link_keys),
                "removed_link_count": len(value.removed_link_keys),
                "changed_link_count": len(value.changed_link_keys),
                "complete": value.complete,
                "digest": value.digest,
                "execution_authority": False,
            },
        }
    if isinstance(value, MetricWindow):
        return {
            "node_id": node_id,
            "result_kind": "metric.window",
            "summary": {
                "concept_id": value.concept_id,
                "resource_id": value.resource_id,
                "unit": value.unit,
                "start": value.start.isoformat(),
                "end": value.end.isoformat(),
                "sample_count": len(value.samples),
                "complete": value.complete,
                "missing_reason": value.missing_reason,
                "execution_authority": False,
            },
        }
    if isinstance(value, CausalEvidenceJoin):
        claim = value.temporal_claim
        return {
            "node_id": node_id,
            "result_kind": "causal.join",
            "summary": {
                "status": value.status.value,
                "topology_diff_digest": value.topology_diff_digest,
                "competing_explanations": list(value.competing_explanations),
                "limitations": list(value.limitations),
                "temporal_claim": None
                if claim is None
                else {
                    "claim_id": claim.claim_id,
                    "cause_metric": claim.cause_metric,
                    "effect_metric": claim.effect_metric,
                    "lag_seconds": claim.lag_seconds,
                    "sample_count": claim.sample_count,
                    "correlation": claim.correlation,
                    "reverse_correlation": claim.reverse_correlation,
                    "adjusted_p_value": claim.adjusted_p_value,
                    "evidence_grade": claim.evidence_grade.value,
                    "feature_cutoff": claim.feature_cutoff.isoformat(),
                    "confounder_metric": claim.confounder_metric,
                    "falsifiers": list(claim.falsifiers),
                },
                "execution_authority": False,
            },
        }
    return None


def _answer_output(
    *,
    node_id: str,
    table: QueryTable,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "rows": rows,
        "returned_rows": len(rows),
        "total_rows": len(table.rows),
        "source_complete": table.complete,
        "source_truncation_reason": table.truncation_reason,
        "display_truncated": len(rows) < len(table.rows),
    }


def _answer_json(outputs: list[dict[str, object]]) -> str:
    return json.dumps(
        {"outputs": outputs},
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _terminal_answer(locale: str, disposition: str, reason_code: str) -> str:
    messages = {
        "answered": "The ontology query completed.",
        "held": "The ontology query was held because verified evidence is unavailable.",
        "clarification": "The ontology query needs clarification before it can run.",
        "unsupported": "The requested ontology query is unsupported.",
        "action_draft": "The request produced a review-only action draft.",
        "cancelled": "The ontology query was cancelled.",
    }
    korean = {
        "answered": "온톨로지 쿼리가 완료되었습니다.",
        "held": "검증된 근거를 사용할 수 없어 온톨로지 쿼리를 보류했습니다.",
        "clarification": "온톨로지 쿼리를 실행하려면 추가 확인이 필요합니다.",
        "unsupported": "요청한 온톨로지 쿼리는 지원되지 않습니다.",
        "action_draft": "요청을 검토 전용 작업 초안으로 만들었습니다.",
        "cancelled": "온톨로지 쿼리가 취소되었습니다.",
    }
    selected = korean if locale.casefold().startswith("ko") else messages
    return f"{selected.get(disposition, selected['held'])} ({reason_code})"


def _request_digest(
    envelope: Mapping[str, Any],
    request: SemanticTurnRequest,
) -> str:
    return content_digest(
        {
            "request_id": envelope["request_id"],
            "correlation_id": envelope["correlation_id"],
            "resource_ref": envelope.get("resource_ref"),
            "requested_at": envelope["requested_at"],
            "semantic_turn": request.model_dump(mode="json"),
        }
    )


async def _release_claim(
    store: SemanticTurnResultStore,
    *,
    idempotency_key: str,
    request_digest: str,
    claim_id: str,
) -> None:
    try:
        await store.release(idempotency_key, request_digest, claim_id)
    except Exception:  # noqa: BLE001 - claim cleanup failure retains fail-closed outcome
        return


def _canonical_projection(encoded: bytes, *, request_digest: str) -> bytes:
    loaded = json.loads(encoded)
    if not isinstance(loaded, dict):
        raise ValueError("stored semantic projection MUST be an object")
    projection_payload = loaded.get("payload")
    if not isinstance(projection_payload, dict):
        raise ValueError("stored semantic projection payload MUST be an object")
    if projection_payload.get("request_digest") != request_digest:
        raise SemanticTurnRejectedError("semantic_idempotency_conflict")
    return OPERATOR_PROJECTION_PRODUCER_V12.encode(loaded)


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SemanticTurnRejectedError(f"{field.replace(' ', '_')}_invalid")
    return value.astimezone(UTC)


__all__ = [
    "SemanticTurnProcessor",
    "SemanticTurnRejectedError",
    "SemanticTurnResultStore",
    "SemanticTurnRuntime",
]
