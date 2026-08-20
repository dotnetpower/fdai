"""Decode and project one bounded Operator semantic turn."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.conversation.semantic_planning_models import BoundIncident
from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.session import Principal, Role, Turn
from fdai.core.ontology_platform import (
    CausalEvidenceJoin,
    MetricWindow,
    MetricWindowComparison,
    QueryPlanExecution,
    TopologyDiff,
    TopologyGraphAt,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    INCIDENT_EVIDENCE_MAX_RECORDS,
)
from fdai.core.ontology_platform.query_values import QueryTable
from fdai_service_contracts import (
    MAX_SEMANTIC_EVIDENCE_REFS,
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

_LOGGER = logging.getLogger(__name__)
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
    "incident_evidence_mismatched_binding",
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
        bound_incident: BoundIncident | None = None,
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
                bound_incident=_bound_incident(request),
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
            _LOGGER.exception("semantic_turn_runtime_failed")
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


def _bound_incident(request: SemanticTurnRequest) -> BoundIncident | None:
    """Expose the conversation's incident identity to planning as trusted input."""
    binding = request.bound_context
    if (
        binding is None
        or binding.kind != "incident"
        or binding.incident_id is None
        or binding.correlation_id is None
    ):
        return None
    return BoundIncident(
        incident_id=_canonical_incident_id(binding.incident_id),
        correlation_id=binding.correlation_id,
    )


def _canonical_incident_id(value: str) -> str:
    """The evidence function echoes a canonical UUID, so compare against the same form."""
    try:
        return str(UUID(value))
    except ValueError:
        return value


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
    frame = planning.frame
    execution = result.execution
    verified_plan_failure = _verified_plan_failure(result, plan, execution)
    if verified_plan_failure is not None or frame is None or plan is None or execution is None:
        return _evidence_incomplete(request, verified_plan_failure or "plan_missing"), None
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref for receipt in execution.receipts for evidence_ref in receipt.evidence_refs
        )
    )
    if not evidence_refs:
        return _evidence_incomplete(request, "no_evidence_refs"), None
    if len(evidence_refs) > MAX_SEMANTIC_EVIDENCE_REFS:
        return _evidence_incomplete(request, "too_many_evidence_refs"), None
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
        return _evidence_incomplete(request, "rule_search_projection_rejected"), None
    incident_found, incident_evidence, incident_node_id = _project_incident_evidence(
        result,
        execution,
    )
    if incident_found and incident_evidence is None:
        return _evidence_incomplete(request, "incident_evidence_projection_rejected"), None
    unsatisfied_binding = _unsatisfied_incident_binding(request, incident_evidence)
    if unsatisfied_binding is not None:
        return _terminal_result(
            request,
            "held",
            unsatisfied_binding,
            answer=_incident_binding_hold_answer(request.locale),
        ), None
    relationships_found, relationships, relationships_node_id = project_ontology_relationships(
        result,
        execution,
    )
    if relationships_found and relationships is None:
        return _evidence_incomplete(request, "relationship_projection_rejected"), None
    answer, technical_details = _render_query_answer(
        request,
        execution,
        operation=frame.operation.value,
        output_shape=frame.output_shape,
        rule_search=rule_search,
        rule_search_node_id=rule_search_node_id,
        incident_evidence=incident_evidence,
        incident_node_id=incident_node_id,
        ontology_relationships=relationships,
        ontology_relationships_node_id=relationships_node_id,
    )
    if answer is None or technical_details is None:
        return _evidence_incomplete(request, "answer_rendering_rejected"), None
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


def _unsatisfied_incident_binding(
    request: SemanticTurnRequest,
    incident_evidence: dict[str, object] | None,
) -> str | None:
    """Reject incident evidence read for an incident other than the bound one.

    The binding rides every turn of an incident conversation, including questions
    that are not about the incident, so a plan that read no incident evidence is
    not by itself a defect.
    """
    binding = request.bound_context
    if (
        binding is None
        or binding.kind != "incident"
        or binding.incident_id is None
        or binding.correlation_id is None
        or incident_evidence is None
    ):
        return None
    if (
        incident_evidence.get("incident_id") != _canonical_incident_id(binding.incident_id)
        or incident_evidence.get("correlation_id") != binding.correlation_id
    ):
        return "incident_evidence_mismatched_binding"
    return None


def _incident_binding_hold_answer(locale: str) -> str:
    if locale.casefold().startswith("ko"):
        return (
            "## 다른 인시던트의 근거를 읽었습니다\n\n"
            "이 대화는 특정 인시던트에 묶여 있지만, 검증된 조회 계획이 다른 인시던트의 "
            "감사 근거를 읽었습니다.\n\n"
            "## 제한 사항\n\n"
            "- 그 결과로 답하면 이 인시던트에 대한 답변으로 오인될 수 있어 보류했습니다.\n\n"
            "## 다음 안전 단계\n\n"
            "질문에 대상 인시던트 식별자를 명시하세요. "
            "이 결과는 읽기 전용이며 실행 권한을 부여하지 않습니다."
        )
    return (
        "## Evidence from a different incident was read\n\n"
        "This conversation is bound to one incident, but the verified query plan read a "
        "different incident's audit evidence.\n\n"
        "## Limitations\n\n"
        "- The result is held because answering from it would read as an answer about this "
        "incident.\n\n"
        "## Next safe step\n\n"
        "Name the intended incident identifier in the question. "
        "This result is read-only and grants no execution authority."
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


def _reject_incident_evidence(reason: str) -> tuple[bool, dict[str, object] | None, str | None]:
    """Name why an incident read failed closed; the wire reason stays unchanged."""
    _LOGGER.warning("incident_evidence_projection_rejected", extra={"failure_type": reason})
    return True, None, None


def _project_incident_evidence(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> tuple[bool, dict[str, object] | None, str | None]:
    plan = result.planning.plan
    if plan is None:
        return _reject_incident_evidence("plan_missing")
    incident_nodes: list[tuple[object, dict[str, Any]]] = []
    for node in getattr(plan, "nodes", ()):
        if getattr(node, "node_id", None) not in execution.output_node_ids:
            continue
        try:
            arguments = node.arguments
        except Exception:  # noqa: BLE001, S112 - malformed plan output fails closed
            continue
        if (
            isinstance(arguments, dict)
            and arguments.get("function_name") == INCIDENT_EVIDENCE_FUNCTION_NAME
        ):
            incident_nodes.append((node, arguments))
    if not incident_nodes:
        return False, None, None
    if len(incident_nodes) != 1:
        return _reject_incident_evidence("multiple_incident_nodes")
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
        return _reject_incident_evidence("node_receipt_mismatch")
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
        or not 1 <= limit <= INCIDENT_EVIDENCE_MAX_RECORDS
        or value.get("incident_id") != _canonical_incident_id(incident_id)
        or value.get("correlation_id") != correlation_id
        or value.get("authority") != "audit_projection"
        or not isinstance(value.get("cause_claim_supported"), bool)
        or value.get("execution_authority") is not False
        or _contains_key(
            {key: item for key, item in value.items() if key != "root_cause"},
            "cause",
        )
    ):
        return _reject_incident_evidence("argument_or_authority_mismatch")
    profile = value.get("incident_profile")
    evidence = value.get("correlated_evidence")
    root_cause = value.get("root_cause")
    impacts = value.get("impact_evidence")
    citations = value.get("grounded_citations")
    gaps = value.get("evidence_gaps")
    evidence_refs = value.get("evidence_refs")
    truncated = value.get("truncated")
    if (
        (profile is not None and not isinstance(profile, dict))
        or not isinstance(evidence, list)
        or len(evidence) > limit
        or (root_cause is not None and not isinstance(root_cause, dict))
        or not isinstance(impacts, list)
        or len(impacts) > limit
        or not isinstance(citations, list)
        or len(citations) > limit
        or not isinstance(gaps, list)
        or not isinstance(evidence_refs, list)
        or not isinstance(truncated, bool)
        or any(not isinstance(item, dict) for item in evidence)
        or any(not isinstance(item, dict) for item in impacts)
        or any(not isinstance(item, dict) for item in citations)
        or any(not isinstance(item, str) for item in gaps)
        or any(not isinstance(item, str) for item in evidence_refs)
    ):
        return _reject_incident_evidence("evidence_shape_invalid")
    # The profile's identity anchor comes from the sampled audit window, so a record
    # naming the incident can fall outside it. An absent anchor is an evidence gap;
    # only an anchor naming a different incident contradicts the request.
    profile_incident_id = profile.get("incident_id") if profile is not None else None
    if profile is not None and (
        (
            profile_incident_id is not None
            and profile_incident_id != _canonical_incident_id(incident_id)
        )
        or profile.get("correlation_id") != correlation_id
    ):
        return _reject_incident_evidence("profile_identity_mismatch")
    audit_refs = [item.get("audit_ref") for item in evidence]
    if any(not isinstance(item, str) for item in audit_refs) or audit_refs != evidence_refs:
        return _reject_incident_evidence("audit_ref_mismatch")
    if not _evidence_is_oldest_first(evidence):
        return _reject_incident_evidence("evidence_order_invalid")
    if truncated and "correlated_audit_truncated" not in gaps:
        return _reject_incident_evidence("truncation_gap_missing")
    supported = value["cause_claim_supported"]
    root_cause_valid = _recorded_root_cause_is_grounded(root_cause, citations)
    expected_gaps = {
        "root_cause_missing": root_cause is None,
        "impact_evidence_missing": not impacts,
        "grounded_citations_missing": not citations,
    }
    if (
        supported is not root_cause_valid
        or (root_cause is None) != ("root_cause_missing" in gaps)
        or any((key in gaps) is not missing for key, missing in expected_gaps.items())
    ):
        return _reject_incident_evidence("rca_evidence_inconsistent")
    return True, value, node_id


def _recorded_root_cause_is_grounded(
    root_cause: object,
    citations: object,
) -> bool:
    if not isinstance(root_cause, Mapping) or not isinstance(citations, list) or not citations:
        return False
    cause = root_cause.get("cause")
    return (
        root_cause.get("outcome") == "grounded"
        and isinstance(cause, str)
        and bool(cause.strip())
        and all(
            isinstance(citation, Mapping)
            and isinstance(citation.get("kind"), str)
            and bool(citation["kind"])
            and isinstance(citation.get("ref"), str)
            and bool(citation["ref"])
            for citation in citations
        )
    )


def _evidence_is_oldest_first(evidence: list[Any]) -> bool:
    """The answer names the latest records by slicing the tail, so the order is a claim."""
    previous: datetime | None = None
    for item in evidence:
        recorded_at = item.get("recorded_at")
        if not isinstance(recorded_at, str):
            return False
        try:
            current = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if current.tzinfo is None or (previous is not None and current < previous):
            return False
        previous = current
    return True


def _contains_key(value: object, key: str) -> bool:
    if isinstance(value, Mapping):
        return key in value or any(_contains_key(item, key) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_contains_key(item, key) for item in value)
    return False


def _verified_plan_failure(
    result: RuntimeSemanticTurnResult,
    plan: object | None,
    execution: QueryPlanExecution | None,
) -> str | None:
    """Name the first unmet answer precondition so a hold is attributable."""
    planning = result.planning
    if plan is None:
        return "plan_missing"
    if execution is None:
        return "execution_missing"
    if result.intent_graph is None or result.intent_graph_evidence is None:
        return "intent_graph_missing"
    if planning.manifest_digest is None:
        return "manifest_digest_missing"
    if planning.manifest_digest != getattr(plan, "semantic_catalog_digest", None):
        return "manifest_digest_mismatch"
    if execution.plan_digest != getattr(plan, "plan_digest", None):
        return "plan_digest_mismatch"
    if execution.status != "completed":
        return "execution_not_completed"
    if not execution.receipts:
        return "no_receipts"
    if any(receipt.status is not TaskStatus.COMPLETED for receipt in execution.receipts):
        return "receipt_not_completed"
    if not _projected_answer_evidence_is_complete(result, execution):
        return "intent_graph_evidence_mismatch"
    return None


def _evidence_incomplete(
    request: SemanticTurnRequest,
    failure_type: str,
) -> ContractSemanticTurnResult:
    _LOGGER.warning("semantic_turn_evidence_incomplete", extra={"failure_type": failure_type})
    return _terminal_result(request, "held", "semantic_evidence_incomplete")


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
    operation: str,
    output_shape: str,
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
        "presentation_context": {
            "operation": operation,
            "output_shape": output_shape,
        },
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
        "verified_records": len(raw_evidence),
        "root_cause": incident_evidence["root_cause"],
        "impact_evidence": incident_evidence["impact_evidence"],
        "grounded_citations": incident_evidence["grounded_citations"],
        "evidence_gaps": incident_evidence["evidence_gaps"],
        "source_truncated": incident_evidence["truncated"],
        "display_truncated": len(displayed) < len(raw_evidence),
        "next_safe_step": {
            "operation": "collect_evidence",
            "authority": "read_only",
            "execution_authority": False,
        },
    }


def _humanized_gap(gap: str, *, korean: bool) -> str:
    """Never surface a raw gap key: Markdown reads its underscores as emphasis."""
    labels = (
        {
            "root_cause_missing": "근거에 기반한 근본 원인 가설",
            "impact_evidence_missing": "영향 근거",
            "grounded_citations_missing": "근거 인용",
            "incident_profile_missing": "인시던트 프로파일",
            "correlated_audit_truncated": "잘리지 않은 감사 기록",
        }
        if korean
        else {
            "root_cause_missing": "a grounded root-cause hypothesis",
            "impact_evidence_missing": "impact evidence",
            "grounded_citations_missing": "grounded citations",
            "incident_profile_missing": "the incident profile",
            "correlated_audit_truncated": "untruncated audit records",
        }
    )
    known = labels.get(gap)
    if known is not None:
        return known
    readable = gap.replace("_", " ").strip()
    return readable or gap


_INCIDENT_GAP_NEXT_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "incident_profile_missing",
        "이 상관관계에 인시던트 레코드가 존재하는지 확인하세요",
        "confirm an incident record exists for this correlation",
    ),
    (
        "root_cause_missing",
        "근거 인용이 포함된 RCA 가설이 기록되었는지 확인하세요",
        "confirm that an RCA hypothesis with grounded citations has been recorded",
    ),
    (
        "impact_evidence_missing",
        "영향받은 리소스의 영향 근거를 수집하세요",
        "collect impact evidence for the affected resources",
    ),
    (
        "grounded_citations_missing",
        "각 주장을 감사 기록에 연결하는 근거 인용을 수집하세요",
        "collect grounded citations that link each claim to an audit record",
    ),
    (
        "correlated_audit_truncated",
        "더 높은 레코드 한도로 이 조회를 다시 실행하세요",
        "re-run this query with a higher record limit",
    ),
)


def incident_next_step_actions(
    gaps: Sequence[str],
    *,
    korean: bool,
) -> tuple[str, ...]:
    """Derive concrete read-only steps from the gaps this answer actually found."""
    present = set(gaps)
    return tuple(
        korean_step if korean else english_step
        for key, korean_step, english_step in _INCIDENT_GAP_NEXT_STEPS
        if key in present
    )


def _incident_next_step_text(
    gaps: Sequence[str],
    *,
    korean: bool,
    root_cause: object = None,
) -> str:
    actions = incident_next_step_actions(gaps, korean=korean)
    if not actions:
        if (
            isinstance(root_cause, Mapping)
            and root_cause.get("next_safe_step") == "configure_notification_route"
        ):
            return (
                "알림 전달을 다시 시도하기 전에 notification registry에 운영 알림 채널을 "
                "하나 이상 구성하세요."
                if korean
                else (
                    "Before retrying delivery, configure at least one operational-alert channel "
                    "in the notification registry."
                )
            )
        return (
            "상관된 감사 근거가 완전합니다. 변경을 제안하기 전에 기록된 활동을 검토하세요."
            if korean
            else (
                "The correlated audit evidence is complete. "
                "Review the recorded activity before proposing a change."
            )
        )
    if korean:
        if len(actions) == 1:
            return f"변경을 제안하기 전에 {actions[0]}."
        joined = " ".join(f"{action}." for action in actions)
        return f"변경을 제안하기 전에 다음을 수행하세요. {joined}"
    joined = actions[0] if len(actions) == 1 else ", ".join(actions[:-1]) + f", and {actions[-1]}"
    return f"Before proposing a change, {joined}."


_INCIDENT_PROFILE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("title", "제목", "Title"),
    ("severity", "심각도", "Severity"),
    ("status", "상태", "Status"),
    ("vertical", "버티컬", "Vertical"),
    ("opened_at", "최초 기록", "First recorded"),
    ("last_updated_at", "최종 기록", "Last recorded"),
    ("actors", "관여 주체", "Actors"),
)
_INCIDENT_TIMELINE_ROWS = 10


def _incident_scalar(value: object) -> str | None:
    """Render one profile cell without inventing a value for a missing field."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        parts = [item for item in (_incident_scalar(entry) for entry in value) if item]
        return ", ".join(parts) or None
    return None


def incident_profile_facts(
    profile: object,
    *,
    korean: bool,
) -> tuple[tuple[str, str], ...]:
    """Surface every populated profile field the audit projection already carries."""
    if not isinstance(profile, Mapping):
        return ()
    facts: list[tuple[str, str]] = []
    for key, korean_label, english_label in _INCIDENT_PROFILE_FIELDS:
        rendered = _incident_scalar(profile.get(key))
        if rendered is not None:
            facts.append((korean_label if korean else english_label, rendered))
    return tuple(facts)


def incident_timeline_rows(evidence: object) -> tuple[Mapping[str, str], ...]:
    """Return the most recent bounded audit records in ascending recorded order."""
    if not isinstance(evidence, list):
        return ()
    rows: list[Mapping[str, str]] = []
    for entry in evidence[-_INCIDENT_TIMELINE_ROWS:]:
        if not isinstance(entry, Mapping):
            continue
        recorded_at = _incident_scalar(entry.get("recorded_at"))
        audit_ref = _incident_scalar(entry.get("audit_ref"))
        if recorded_at is None or audit_ref is None:
            continue
        rows.append(
            {
                "recorded_at": recorded_at,
                "actor": _incident_scalar(entry.get("actor")) or "-",
                "action_kind": _incident_scalar(entry.get("action_kind")) or "-",
                "mode": _incident_scalar(entry.get("mode")) or "-",
                "audit_ref": audit_ref,
            }
        )
    return tuple(rows)


def _incident_timeline_markdown(
    rows: tuple[Mapping[str, str], ...],
    *,
    korean: bool,
) -> str:
    if not rows:
        return ""
    header = (
        "| 기록 시각 | 주체 | 활동 | 모드 | 감사 참조 |"
        if korean
        else "| Recorded | Actor | Activity | Mode | Audit ref |"
    )
    lines = [header, "| --- | --- | --- | --- | --- |"]
    lines.extend(
        f"| {row['recorded_at']} | {row['actor']} | {row['action_kind']} "
        f"| {row['mode']} | `{row['audit_ref']}` |"
        for row in rows
    )
    return "\n".join(lines)


def _incident_rca_markdown(
    root_cause: object,
    impacts: object,
    citations: object,
    *,
    korean: bool,
) -> str:
    sections: list[str] = []
    if isinstance(root_cause, Mapping):
        cause = _incident_scalar(root_cause.get("cause"))
        if cause is not None:
            tier = _incident_scalar(root_cause.get("tier")) or "-"
            confidence = _incident_scalar(root_cause.get("confidence")) or "-"
            lines = [
                f"- {'원인' if korean else 'Cause'}: {cause}",
                f"- {'티어' if korean else 'Tier'}: {tier}",
                f"- {'신뢰도' if korean else 'Confidence'}: {confidence}",
            ]
            reason = _incident_scalar(root_cause.get("reason"))
            recorded_at = _incident_scalar(root_cause.get("recorded_at"))
            if reason is not None:
                lines.append(f"- {'근거' if korean else 'Reason'}: {reason}")
            if recorded_at is not None:
                lines.append(f"- {'기록 시각' if korean else 'Recorded'}: {recorded_at}")
            sections.append(f"## {'근본 원인' if korean else 'Root cause'}\n\n" + "\n".join(lines))
    impact_rows = impacts if isinstance(impacts, list) else []
    if impact_rows:
        header = (
            "| 메트릭 | 기준 | 관측 | 임계값 | 단위 | 영향 | 근거 |"
            if korean
            else "| Metric | Baseline | Observed | Threshold | Unit | Impact | Evidence |"
        )
        lines = [header, "| --- | --- | --- | --- | --- | --- | --- |"]
        for row in impact_rows[:20]:
            if not isinstance(row, Mapping):
                continue
            values = [
                _incident_markdown_cell(row.get(key))
                for key in (
                    "metric",
                    "baseline",
                    "observed",
                    "threshold",
                    "unit",
                    "impact",
                    "evidence_ref",
                )
            ]
            lines.append("| " + " | ".join(values) + " |")
        sections.append(f"## {'영향 근거' if korean else 'Impact evidence'}\n\n" + "\n".join(lines))
    citation_rows = citations if isinstance(citations, list) else []
    if citation_rows:
        header = (
            "| 티어 | 종류 | 참조 | 요약 | 기록 시각 |"
            if korean
            else "| Tier | Kind | Reference | Summary | Recorded |"
        )
        lines = [header, "| --- | --- | --- | --- | --- |"]
        for row in citation_rows[:20]:
            if not isinstance(row, Mapping):
                continue
            values = [
                _incident_markdown_cell(row.get(key))
                for key in ("tier", "kind", "ref", "summary", "recorded_at")
            ]
            lines.append("| " + " | ".join(values) + " |")
        sections.append(
            f"## {'근거 인용' if korean else 'Grounded citations'}\n\n" + "\n".join(lines)
        )
    return "\n\n".join(sections)


def _incident_markdown_cell(value: object) -> str:
    rendered = _incident_scalar(value) or "-"
    return rendered.replace("|", "\\|").replace("\n", " ")


def _incident_profile_lines(
    facts: tuple[tuple[str, str], ...],
    profile: object,
    *,
    korean: bool,
) -> str:
    """An absent profile, an unrecorded status, and a reported status are three answers.

    Populated fields are listed, but silence about status would read as absence of
    trouble, so an unrecorded status is still stated even when other fields render.
    """
    lines = "".join(f"- {label}: {value}\n" for label, value in facts)
    if profile is None:
        return lines + (
            "- 인시던트 프로파일이 없어 상태를 보고할 수 없습니다.\n"
            if korean
            else "- Status can't be reported because the incident profile is missing.\n"
        )
    status = profile.get("status") if isinstance(profile, Mapping) else None
    if _incident_scalar(status) is None:
        return lines + (
            "- 조회한 감사 기록에 인시던트 상태가 없습니다.\n"
            if korean
            else "- The audit records read for this incident record no status.\n"
        )
    return lines


def _render_incident_answer(
    request: SemanticTurnRequest,
    output: Mapping[str, object],
) -> str:
    evidence = output.get("correlated_evidence")
    profile = output.get("incident_profile")
    root_cause = output.get("root_cause")
    impacts = output.get("impact_evidence")
    citations = output.get("grounded_citations")
    gaps = output.get("evidence_gaps")
    shown = len(evidence) if isinstance(evidence, list) else 0
    verified = output.get("verified_records")
    evidence_count = (
        verified if isinstance(verified, int) and not isinstance(verified, bool) else shown
    )
    gap_values = (
        tuple(item for item in gaps if isinstance(item, str)) if isinstance(gaps, list) else ()
    )
    korean = request.locale.casefold().startswith("ko")
    facts = incident_profile_facts(profile, korean=korean)
    timeline = _incident_timeline_markdown(incident_timeline_rows(evidence), korean=korean)
    rca_sections = _incident_rca_markdown(
        root_cause,
        impacts,
        citations,
        korean=korean,
    )
    timeline_truncated = shown > _INCIDENT_TIMELINE_ROWS
    missing = ", ".join(_humanized_gap(gap, korean=korean) for gap in gap_values) or (
        "없음" if korean else "none"
    )
    if korean:
        found = (
            f"- 상관관계가 있는 감사 기록 {evidence_count}건을 검증했습니다.\n"
            if evidence_count
            else "- 이 상관관계로 조회한 감사 기록이 없습니다.\n"
        )
        if shown < evidence_count:
            found += f"- 아래에는 가장 최근 {shown}건만 담겨 있습니다.\n"
        found += _incident_profile_lines(facts, profile, korean=True)
        timeline_section = (
            "## 기록된 활동\n\n"
            + timeline
            + (
                f"\n\n표에는 가장 최근 {_INCIDENT_TIMELINE_ROWS}건만 담았습니다. "
                f"담긴 {shown}건 전체는 기술 상세에 있습니다.\n\n"
                if timeline_truncated
                else "\n\n"
            )
            if timeline
            else ""
        )
        return (
            "## 검증된 인시던트 근거\n\n"
            f"{found}\n"
            f"{timeline_section}"
            f"{rca_sections + chr(10) + chr(10) if rca_sections else ''}"
            "## 제한 사항\n\n"
            f"- 누락된 근거: {missing}\n\n"
            "## 다음 안전 단계\n\n"
            f"{_incident_next_step_text(gap_values, korean=True, root_cause=root_cause)} "
            "이 결과는 읽기 전용이며 실행 권한을 부여하지 않습니다."
        )
    evidence_label = "record was" if evidence_count == 1 else "records were"
    found = (
        f"- {evidence_count} correlated audit {evidence_label} verified.\n"
        if evidence_count
        else "- No audit record was found for this correlation.\n"
    )
    if shown < evidence_count:
        found += f"- Only the most recent {shown} are carried below.\n"
    found += _incident_profile_lines(facts, profile, korean=False)
    timeline_section = (
        "## Recorded activity\n\n"
        + timeline
        + (
            f"\n\nThe table lists only the most recent {_INCIDENT_TIMELINE_ROWS} records. "
            f"All {shown} carried records are in technical details.\n\n"
            if timeline_truncated
            else "\n\n"
        )
        if timeline
        else ""
    )
    return (
        "## Verified incident evidence\n\n"
        f"{found}\n"
        f"{timeline_section}"
        f"{rca_sections + chr(10) + chr(10) if rca_sections else ''}"
        "## Limitations\n\n"
        f"- Missing evidence: {missing}\n\n"
        "## Next safe step\n\n"
        f"{_incident_next_step_text(gap_values, korean=False, root_cause=root_cause)} "
        "This result is read-only and grants no execution authority."
    )


def _render_general_query_answer(
    request: SemanticTurnRequest,
    outputs: list[dict[str, object]],
) -> str:
    """Report what was verified without naming the plan that produced it.

    A plan node id and the words that describe the query engine are internal
    vocabulary. The operator asked a question, so the answer states what the
    result contains and leaves the machinery in technical details.
    """
    korean = request.locale.casefold().startswith("ko")
    lines = ["## 검증된 결과" if korean else "## Verified result", ""]
    for output in outputs:
        rule_search = output.get("rule_search")
        if isinstance(rule_search, Mapping):
            candidates = rule_search.get("candidates")
            count = len(candidates) if isinstance(candidates, list) else 0
            lines.append(
                f"- 규칙 후보 {count}건을 검증했습니다."
                if korean
                else f"- Verified {count} rule candidates."
            )
            continue
        result_kind = output.get("result_kind")
        if isinstance(result_kind, str):
            lines.append(
                f"- `{result_kind}` 결과를 검증했습니다."
                if korean
                else f"- Verified a `{result_kind}` result."
            )
            continue
        returned = output.get("returned_rows")
        total = output.get("total_rows")
        lines.append(
            f"- 전체 {total}개 행 중 {returned}개를 검증했습니다."
            if korean
            else f"- Verified {returned} of {total} rows."
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
    if isinstance(value, MetricWindowComparison):
        return {
            "node_id": node_id,
            "result_kind": "metric.comparison",
            "summary": {
                "concept_id": value.concept_id,
                "resource_id": value.resource_id,
                "unit": value.unit,
                "baseline_start": value.baseline_start.isoformat(),
                "baseline_end": value.baseline_end.isoformat(),
                "current_start": value.current_start.isoformat(),
                "current_end": value.current_end.isoformat(),
                "baseline_value": value.baseline_value,
                "current_value": value.current_value,
                "absolute_change": value.absolute_change,
                "relative_change": value.relative_change,
                "complete": value.complete,
                "reason": value.reason,
                "execution_authority": False,
            },
        }
    if isinstance(value, CausalEvidenceJoin):
        claim = value.temporal_claim
        return {
            "node_id": node_id,
            "result_kind": "causal.join",
            "summary": {
                "hypothesis_id": node_id.removeprefix("hypothesis-"),
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
        "answered": "The verified result is ready.",
        "held": "The request was held because verified evidence is unavailable.",
        "clarification": "The request needs clarification before it can run.",
        "unsupported": "The request is not supported by a verified capability.",
        "action_draft": "The request produced a review-only action draft.",
        "cancelled": "The request was cancelled.",
    }
    korean = {
        "answered": "검증된 결과를 준비했습니다.",
        "held": "검증된 근거를 사용할 수 없어 요청을 보류했습니다.",
        "clarification": "요청을 수행하려면 추가 확인이 필요합니다.",
        "unsupported": "검증된 기능으로 답할 수 없는 요청입니다.",
        "action_draft": "요청을 검토 전용 작업 초안으로 만들었습니다.",
        "cancelled": "요청이 취소되었습니다.",
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
