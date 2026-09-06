"""Decode and project one bounded Operator semantic turn."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid5

from fdai.core.conversation.intent_graph import resolve_execution_authority
from fdai.core.conversation.semantic_investigation import InvestigationEntityRole
from fdai.core.conversation.semantic_planning_cascade import (
    AGGRESSIVE_T2_ESCALATION_POLICY,
    NO_T2_ESCALATION_POLICY,
    SemanticPlanningEscalationPolicy,
)
from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    BoundInvestigationContinuation,
    BoundResourceContext,
)
from fdai.core.conversation.semantic_runtime import (
    SemanticTurnResult as RuntimeSemanticTurnResult,
)
from fdai.core.conversation.semantic_runtime import optional_document_evidence_degraded
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
from fdai.shared.contracts.models import OntologyDeclarationKind
from fdai_service_contracts import (
    MAX_SEMANTIC_EVIDENCE_REFS,
    OperationalEvidenceProjection,
    OperatorRole,
    RuleSearchProjection,
    RuleSearchRequest,
    SemanticAssuranceObservation,
    SemanticDirectResponseIntent,
    SemanticInvestigationContinuation,
    SemanticPlanningProfile,
    SemanticRoute,
    SemanticTurnDisposition,
    SemanticTurnRequest,
    SemanticUnavailableReason,
    rule_search_query_digest,
)
from fdai_service_contracts import (
    SemanticTurnResult as ContractSemanticTurnResult,
)
from fdai_service_contracts.codec import MAX_WIRE_BYTES
from fdai_service_contracts.ontology_query import (
    MAX_INTENT_GRAPH_GOALS,
    QueryNodeKind,
    TaskStatus,
    content_digest,
)

from fdai_core_service.dialogue_relationship import runtime_relationship

from .contract_codecs import (
    OPERATOR_PROJECTION_PRODUCER_V13,
    OPERATOR_PROJECTION_PRODUCER_V14,
    OPERATOR_PROJECTION_PRODUCER_V16,
    OPERATOR_REQUEST_CONSUMER_V16,
)
from .semantic_assurance_projection import project_semantic_assurance
from .semantic_presentation_semantics import project_presentation_semantics
from .semantic_relationship_projection import (
    project_ontology_relationships,
    render_ontology_relationship_answer,
)
from .semantic_service_health_answer import (
    render_service_health_answer as _render_service_health_answer,
)
from .semantic_subscription_scope_answer import (
    render_subscription_scope_answer as _render_subscription_scope_answer,
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
    "direct_response": "semantic_direct_response",
    "clarification": "semantic_clarification",
    "unsupported": "semantic_unsupported",
    "action_draft": "semantic_action_draft",
    "cancelled": "semantic_cancellation",
}
_AUTHORITATIVE_EVIDENCE_UNAVAILABLE_REASONS = {
    "semantic_evidence_held",
    "semantic_evidence_incomplete",
    "incident_evidence_mismatched_binding",
    "semantic_exact_source_unavailable",
    "semantic_knowledge_source_status_unavailable",
    "operational_evidence_unavailable",
    "operational_evidence_over_budget",
    "semantic_evidence_authority_conflict",
    "semantic_evidence_authority_missing",
    "semantic_current_relationship_mapping_unavailable",
    "semantic_governed_documents_unavailable",
    "semantic_governed_documents_incomplete",
    "semantic_governed_documents_empty",
}
_SEMANTIC_PLANNER_UNAVAILABLE_REASONS = {
    "semantic_frame_unavailable",
}


@dataclass(frozen=True, slots=True)
class _SemanticProjectionExtensions:
    rule_search: RuleSearchProjection | None = None
    technical_details: dict[str, object] | None = None
    model: str | None = None
    latency_ms: int | None = None
    usage: dict[str, int] | None = None
    model_trace: dict[str, object] | None = None
    social_act: str | None = None
    investigation_continuation: SemanticInvestigationContinuation | None = None
    operational_evidence: OperationalEvidenceProjection | None = None


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
        locale: str = "en",
        target_agent: str = "Bragi",
        relationship: Mapping[str, object] | None = None,
        cancelled: asyncio.Event | None = None,
        bound_incident: BoundIncident | None = None,
        bound_resource_context: BoundResourceContext | None = None,
        bound_investigation_continuation: BoundInvestigationContinuation | None = None,
        escalation_policy: SemanticPlanningEscalationPolicy | None = None,
    ) -> RuntimeSemanticTurnResult: ...


class RuntimeSettingsReader(Protocol):
    """Read the current audited runtime policy for one semantic turn."""

    async def effective_values(self) -> dict[str, object]: ...


class SemanticRuntimeReadiness(Protocol):
    """Report a stable per-turn reason when semantic-model identity is unavailable."""

    async def unavailable_reason(self) -> str | None: ...


class PantheonAssuranceRuntime(Protocol):
    """Produce one fixed-census answer and its authoritative diagnostic payload."""

    async def evaluate(
        self,
        request: SemanticTurnRequest,
        *,
        case_id: str,
    ) -> Mapping[str, object]: ...


class OperationalEvidenceProjectionReader(Protocol):
    """Project admitted evidence for one authenticated resource-scoped turn."""

    async def read(
        self,
        *,
        principal_ref: str,
        principal_scope_digest: str,
        purpose: str,
        ontology_release_digest: str,
        catalog_revision: str,
        scope: tuple[str, ...],
        cutoff: datetime,
    ) -> Mapping[str, object]: ...


class _OperationalEvidenceWireBudgetExceededError(RuntimeError):
    """The optional evidence extension cannot fit the shared wire envelope."""


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
        pantheon_assurance: PantheonAssuranceRuntime | None = None,
        operational_evidence: OperationalEvidenceProjectionReader | None = None,
        answer_continuity_enabled: bool = False,
        runtime_settings: RuntimeSettingsReader | None = None,
        runtime_readiness: SemanticRuntimeReadiness | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not purpose:
            raise ValueError("semantic turn purpose MUST be non-empty")
        if not isinstance(answer_continuity_enabled, bool):
            raise ValueError("answer_continuity_enabled MUST be a boolean")
        self._runtime = runtime
        self._results = results
        self._purpose = purpose
        self._pantheon_assurance = pantheon_assurance
        self._operational_evidence = operational_evidence
        self._answer_continuity_enabled = answer_continuity_enabled
        self._runtime_settings = runtime_settings
        self._runtime_readiness = runtime_readiness
        self._now = now or (lambda: datetime.now(UTC))

    def bind_pantheon_assurance(self, runtime: PantheonAssuranceRuntime) -> None:
        """Bind the diagnostic runtime once before consumer tasks start."""

        if self._pantheon_assurance is not None:
            raise RuntimeError("Pantheon conversation assurance is already bound")
        self._pantheon_assurance = runtime

    async def process(
        self,
        payload: Mapping[str, Any],
        *,
        cancelled: asyncio.Event | None = None,
    ) -> bytes:
        """Return one canonical v1.2 projection or reject invalid boundary input."""

        envelope, request, requested_at = _decode_request(payload)
        principal = _principal(request)
        assurance_case_id = _pantheon_assurance_case_id(request.purpose)
        if request.purpose != self._purpose and assurance_case_id is None:
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
                assurance_case_id=assurance_case_id,
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
        assurance_case_id: str | None,
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
            winner, claim_id = await self._wait_for_claimed_projection(
                envelope=envelope,
                request=request,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
            )
            if winner is not None:
                return winner
            if claim_id is None:
                return self._held_projection(
                    envelope,
                    request,
                    request_digest=request_digest,
                    reason_code="semantic_result_store_unavailable",
                )

        claim_finalized = False
        try:
            try:
                if assurance_case_id is None:
                    result, extensions = await self._execute(
                        request=request,
                        requested_at=requested_at,
                        principal=principal,
                        cancelled=cancelled,
                    )
                    try:
                        projection = self._projection(
                            envelope,
                            request,
                            result,
                            extensions=extensions,
                            request_digest=request_digest,
                        )
                    except _OperationalEvidenceWireBudgetExceededError:
                        projection = self._projection(
                            envelope,
                            request,
                            self._with_answer_continuity(
                                request,
                                _terminal_result(
                                    request,
                                    "held",
                                    "operational_evidence_over_budget",
                                ),
                            ),
                            extensions=None,
                            request_digest=request_digest,
                        )
                else:
                    projection = await self._pantheon_assurance_projection(
                        envelope,
                        request,
                        case_id=assurance_case_id,
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
    ) -> tuple[bytes | None, str | None]:
        delay = 0.01
        while True:
            await asyncio.sleep(delay)
            try:
                winner = await self._results.get(idempotency_key)
            except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
                return (
                    self._held_projection(
                        envelope,
                        request,
                        request_digest=request_digest,
                        reason_code="semantic_result_store_unavailable",
                    ),
                    None,
                )
            if winner is None:
                try:
                    recovered_claim = await self._results.claim(
                        idempotency_key,
                        request_digest,
                    )
                except SemanticTurnRejectedError:
                    raise
                except Exception:  # noqa: BLE001 - persistence detail must not cross the wire
                    return (
                        self._held_projection(
                            envelope,
                            request,
                            request_digest=request_digest,
                            reason_code="semantic_result_store_unavailable",
                        ),
                        None,
                    )
                if recovered_claim is not None:
                    return None, recovered_claim
                delay = min(delay * 2, 0.25)
                continue
            try:
                return _canonical_projection(winner, request_digest=request_digest), None
            except SemanticTurnRejectedError:
                raise
            except Exception:  # noqa: BLE001 - corrupt persistence fails closed
                return (
                    self._held_projection(
                        envelope,
                        request,
                        request_digest=request_digest,
                        reason_code="semantic_result_store_unavailable",
                    ),
                    None,
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
            return (
                self._with_answer_continuity(
                    request,
                    _terminal_result(request, "held", "semantic_deadline_exceeded"),
                ),
                None,
            )
        if self._runtime is None:
            return (
                self._with_answer_continuity(
                    request,
                    _terminal_result(request, "held", "semantic_runtime_unavailable"),
                ),
                None,
            )
        if self._runtime_readiness is not None:
            unavailable_reason = await self._runtime_readiness.unavailable_reason()
            if unavailable_reason is not None:
                return (
                    self._with_answer_continuity(
                        request,
                        _terminal_result(request, "held", unavailable_reason),
                    ),
                    None,
                )

        runtime_cancelled = asyncio.Event()
        bound_resource_context = _bound_resource_context(request)
        runtime_task = asyncio.create_task(
            self._handle_runtime(
                request=request,
                requested_at=requested_at,
                principal=principal,
                runtime_cancelled=runtime_cancelled,
                bound_resource_context=bound_resource_context,
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
                return (
                    self._with_answer_continuity(
                        request,
                        _terminal_result(request, "held", "semantic_deadline_exceeded"),
                    ),
                    None,
                )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            runtime_result = runtime_task.result()
            result, extensions = _project_runtime_result(request, runtime_result)
            result, extensions = await self._bind_operational_evidence(
                request=request,
                runtime_result=runtime_result,
                result=result,
                extensions=extensions,
            )
            return self._with_answer_continuity(request, result), extensions
        except asyncio.CancelledError:
            runtime_cancelled.set()
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
            raise
        except Exception:  # noqa: BLE001 - runtime/provider detail must not cross the wire
            _LOGGER.exception("semantic_turn_runtime_failed")
            return (
                self._with_answer_continuity(
                    request,
                    _terminal_result(request, "held", "semantic_runtime_failed"),
                ),
                None,
            )
        finally:
            if cancellation_task is not None and not cancellation_task.done():
                cancellation_task.cancel()
                await asyncio.gather(cancellation_task, return_exceptions=True)

    async def _handle_runtime(
        self,
        *,
        request: SemanticTurnRequest,
        requested_at: datetime,
        principal: Principal,
        runtime_cancelled: asyncio.Event,
        bound_resource_context: BoundResourceContext | None,
    ) -> RuntimeSemanticTurnResult:
        runtime = self._runtime
        if runtime is None:  # pragma: no cover - guarded by _execute
            raise RuntimeError("semantic runtime is unavailable")
        runtime_kwargs: dict[str, Any] = {}
        relationship = runtime_relationship(request, now=self._now())
        if relationship is not None:
            runtime_kwargs["relationship"] = relationship
        if bound_resource_context is not None:
            runtime_kwargs["bound_resource_context"] = bound_resource_context
        escalation_policy = await self._escalation_policy(request)
        if escalation_policy is not None:
            runtime_kwargs["escalation_policy"] = escalation_policy
        return await runtime.handle(
            utterance=request.utterance,
            prior_turns=_prior_turns(request, requested_at=requested_at),
            principal=principal,
            locale=request.locale,
            target_agent=request.target_agent,
            cancelled=runtime_cancelled,
            bound_incident=_bound_incident(request),
            bound_investigation_continuation=_bound_investigation_continuation(request),
            **runtime_kwargs,
        )

    async def _escalation_policy(
        self,
        request: SemanticTurnRequest,
    ) -> SemanticPlanningEscalationPolicy | None:
        if request.planning_profile is SemanticPlanningProfile.GOLDEN_CAMPAIGN_NO_T2:
            _LOGGER.info(
                "semantic_t2_aggressive_policy_evaluated",
                extra={"enabled": False, "reason": "planning_profile_no_t2"},
            )
            return NO_T2_ESCALATION_POLICY
        if self._runtime_settings is None:
            return None
        try:
            values = await self._runtime_settings.effective_values()
        except (RuntimeError, ValueError) as exc:
            _LOGGER.warning(
                "semantic_t2_aggressive_policy_unavailable",
                extra={"failure_type": type(exc).__name__},
            )
            return None
        enabled = values.get("conversation.t2_escalation.aggressive_enabled")
        if not isinstance(enabled, bool):
            _LOGGER.warning(
                "semantic_t2_aggressive_policy_unavailable",
                extra={"failure_type": "InvalidSettingValue"},
            )
            return None
        _LOGGER.info(
            "semantic_t2_aggressive_policy_evaluated",
            extra={"enabled": enabled, "reason": "runtime_setting"},
        )
        return AGGRESSIVE_T2_ESCALATION_POLICY if enabled else None

    async def _bind_operational_evidence(
        self,
        *,
        request: SemanticTurnRequest,
        runtime_result: RuntimeSemanticTurnResult,
        result: ContractSemanticTurnResult,
        extensions: _SemanticProjectionExtensions | None,
    ) -> tuple[ContractSemanticTurnResult, _SemanticProjectionExtensions | None]:
        reader = self._operational_evidence
        binding = request.bound_context
        if (
            reader is None
            or result.disposition is not SemanticTurnDisposition.ANSWERED
            or binding is None
            or binding.kind not in {"screen", "resource_group"}
        ):
            return result, extensions
        plan = runtime_result.planning.plan
        if (
            plan is None
            or binding.principal_id != request.principal.subject_id
            or binding.principal_scope_digest is None
            or binding.ontology_release_digest != plan.ontology_release_digest
            or not binding.resource_ids
        ):
            return (
                _terminal_result(request, "held", "operational_evidence_unavailable"),
                None,
            )
        try:
            projected = await reader.read(
                principal_ref=request.principal.subject_id,
                principal_scope_digest=binding.principal_scope_digest,
                purpose=request.purpose,
                ontology_release_digest=plan.ontology_release_digest,
                catalog_revision=plan.semantic_catalog_digest,
                scope=binding.resource_ids,
                cutoff=_aware_utc(self._now(), field="operational evidence cutoff"),
            )
            evidence = OperationalEvidenceProjection.model_validate(projected)
        except (ValueError, RuntimeError):
            _LOGGER.warning(
                "semantic_operational_evidence_unavailable",
                extra={
                    "reason_code": "operational_evidence_unavailable",
                    "turn_id": request.turn_id,
                },
            )
            return (
                _terminal_result(request, "held", "operational_evidence_unavailable"),
                None,
            )
        return result, _merge_projection_extensions(
            extensions,
            _SemanticProjectionExtensions(operational_evidence=evidence),
        )

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
        projection_time = _aware_utc(self._now(), field="semantic processor clock")
        recorded_at = projection_time.replace(
            microsecond=(projection_time.microsecond // 1000) * 1000,
        )
        payload: dict[str, object] = {
            "request_kind": "semantic_query",
            "request_digest": request_digest,
            "turn_timing": _semantic_turn_timing(
                envelope=envelope,
                result=result,
                completed_at=recorded_at,
            ),
        }
        if extensions is not None:
            if extensions.rule_search is not None:
                payload["rule_search"] = extensions.rule_search.model_dump(mode="json")
            if extensions.technical_details is not None:
                payload["technical_details"] = extensions.technical_details
            if extensions.model is not None:
                payload["model"] = extensions.model
            if extensions.latency_ms is not None:
                payload["latency_ms"] = extensions.latency_ms
            if extensions.usage is not None:
                payload["usage"] = extensions.usage
            if extensions.model_trace is not None:
                payload["model_trace"] = extensions.model_trace
            if extensions.social_act is not None:
                payload["social_act"] = extensions.social_act
            if extensions.investigation_continuation is not None:
                payload["investigation_continuation"] = (
                    extensions.investigation_continuation.model_dump(mode="json")
                )
            if extensions.operational_evidence is not None:
                payload["operational_evidence"] = extensions.operational_evidence.model_dump(
                    mode="json"
                )
        projection = {
            "schema_version": ("1.6.0" if result.adaptive_answer is not None else "1.4.0"),
            "request_id": envelope["request_id"],
            "correlation_id": envelope["correlation_id"],
            "idempotency_key": envelope["idempotency_key"],
            "status": result.disposition.value,
            "recorded_at": recorded_at.isoformat(timespec="milliseconds"),
            "payload": payload,
            "evidence_digest": evidence_digest,
            "semantic_result": semantic_result,
        }
        projection["projection_id"] = _semantic_projection_id(projection)
        if extensions is not None and extensions.operational_evidence is not None:
            encoded_size = len(
                json.dumps(
                    projection,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            )
            if encoded_size > MAX_WIRE_BYTES:
                raise _OperationalEvidenceWireBudgetExceededError
        codec = (
            OPERATOR_PROJECTION_PRODUCER_V16
            if projection["schema_version"] == "1.6.0"
            else OPERATOR_PROJECTION_PRODUCER_V14
        )
        return codec.encode(projection)

    async def _pantheon_assurance_projection(
        self,
        envelope: Mapping[str, Any],
        request: SemanticTurnRequest,
        *,
        case_id: str,
        request_digest: str,
    ) -> bytes:
        runtime = self._pantheon_assurance
        if runtime is None:
            return self._held_projection(
                envelope,
                request,
                request_digest=request_digest,
                reason_code="semantic_runtime_unavailable",
            )
        result = dict(await runtime.evaluate(request, case_id=case_id))
        _validate_pantheon_assurance_result(result)
        evidence_digest = content_digest(
            {
                "assessment_id": result["assessment_id"],
                "trace_receipt_id": result["trace_receipt_id"],
                "pantheon_diagnostic": result["pantheon_diagnostic"],
            }
        )
        projection_time = _aware_utc(self._now(), field="semantic processor clock")
        recorded_at = projection_time.replace(
            microsecond=(projection_time.microsecond // 1000) * 1000,
        )
        fallback = self._with_answer_continuity(
            request,
            _terminal_result(
                request,
                "held",
                "semantic_runtime_unavailable",
            ),
        ).model_dump(mode="json", exclude_none=True)
        projection = {
            "schema_version": "1.4.0",
            "request_id": envelope["request_id"],
            "correlation_id": envelope["correlation_id"],
            "idempotency_key": envelope["idempotency_key"],
            "status": "held",
            "recorded_at": recorded_at.isoformat(timespec="milliseconds"),
            "payload": {
                "request_kind": "pantheon_conversation_assurance",
                "request_digest": request_digest,
                "pantheon_assurance": result,
            },
            "evidence_digest": evidence_digest,
            # Keep the current semantic result shape so an older Operator
            # consumer safely renders a hold during a consumer-first rollout.
            "semantic_result": fallback,
        }
        projection["projection_id"] = _semantic_projection_id(projection)
        return OPERATOR_PROJECTION_PRODUCER_V14.encode(projection)

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
            self._with_answer_continuity(
                request,
                _terminal_result(request, disposition, reason_code),
            ),
            extensions=None,
            request_digest=request_digest,
        )

    def _with_answer_continuity(
        self,
        request: SemanticTurnRequest,
        result: ContractSemanticTurnResult,
    ) -> ContractSemanticTurnResult:
        if not self._answer_continuity_enabled or result.disposition not in {
            SemanticTurnDisposition.HELD,
            SemanticTurnDisposition.UNSUPPORTED,
        }:
            return result
        strict_answer = _terminal_answer(
            request.locale,
            result.disposition.value,
            result.reason_code,
        )
        if result.answer != strict_answer:
            return result
        return result.model_copy(
            update={
                "answer": _continuity_terminal_answer(
                    request.locale,
                    result.disposition.value,
                    result.reason_code,
                    unavailable_reason=result.unavailable_reason,
                )
            }
        )


def _decode_request(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], SemanticTurnRequest, datetime]:
    try:
        envelope = OPERATOR_REQUEST_CONSUMER_V16.decode_mapping(payload)
        if envelope.get("request_kind") != "semantic_query":
            raise SemanticTurnRejectedError("semantic_request_kind_required")
        semantic_turn = envelope.get("semantic_turn")
        if not isinstance(semantic_turn, dict):
            raise SemanticTurnRejectedError("semantic_turn_required")
        request = SemanticTurnRequest.model_validate(semantic_turn)
        _validate_investigation_continuation(request)
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
    return Principal(
        id=request.principal.subject_id,
        role=_ROLE_MAP[selected],
        groups=frozenset(request.principal.groups),
    )


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


def _bound_resource_context(request: SemanticTurnRequest) -> BoundResourceContext | None:
    """Expose only the exact server-selected screen or group scope to planning."""
    binding = request.bound_context
    if binding is None or binding.kind == "incident":
        return None
    if binding.kind == "screen" and binding.screen_id is not None:
        return BoundResourceContext(
            kind="screen",
            screen_id=binding.screen_id,
            resource_ids=binding.resource_ids,
            principal_id=binding.principal_id or "",
            principal_scope_digest=binding.principal_scope_digest or "",
            ontology_release_digest=binding.ontology_release_digest or "",
            source_generation=binding.source_generation or "",
            selection_digest=binding.selection_digest or "",
            selection_token=binding.selection_token or "",
            complete=binding.complete is True,
        )
    if binding.kind == "resource_group" and binding.resource_group_id is not None:
        return BoundResourceContext(
            kind="resource_group",
            resource_group_id=binding.resource_group_id,
            resource_ids=binding.resource_ids,
            principal_id=binding.principal_id or "",
            principal_scope_digest=binding.principal_scope_digest or "",
            ontology_release_digest=binding.ontology_release_digest or "",
            source_generation=binding.source_generation or "",
            selection_digest=binding.selection_digest or "",
            selection_token=binding.selection_token or "",
            complete=binding.complete is True,
        )
    return None


def _validate_investigation_continuation(request: SemanticTurnRequest) -> None:
    continuation = request.investigation_continuation
    if continuation is None:
        return
    if (
        continuation.source_session_id != request.session_id
        or continuation.source_turn_sequence >= request.turn_sequence
    ):
        raise SemanticTurnRejectedError("semantic_investigation_continuation_mismatched")


def _bound_investigation_continuation(
    request: SemanticTurnRequest,
) -> BoundInvestigationContinuation | None:
    continuation = request.investigation_continuation
    if continuation is None:
        return None
    return BoundInvestigationContinuation(
        source_session_id=continuation.source_session_id,
        source_turn_id=continuation.source_turn_id,
        source_turn_sequence=continuation.source_turn_sequence,
        target_type=continuation.target_type,
        target_value=continuation.target_value,
        recovery_measure_concepts=continuation.recovery_measure_concepts,
        baseline_start=continuation.baseline_start,
        baseline_end=continuation.baseline_end,
        initial_observation_cutoff=continuation.initial_observation_cutoff,
        ontology_release_digest=continuation.ontology_release_digest,
        principal_manifest_digest=continuation.principal_manifest_digest,
        source_frame_digest=continuation.source_frame_digest,
        source_plan_digest=continuation.source_plan_digest,
        source_execution_receipt_digest=continuation.source_execution_receipt_digest,
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
    model_extensions = _semantic_model_extensions(request, result)
    if result.disposition == "advisory_response":
        adaptive_answer = result.adaptive_answer
        if adaptive_answer is None:
            return _terminal_result(request, "held", "semantic_runtime_failed"), model_extensions
        return (
            ContractSemanticTurnResult(
                disposition=SemanticTurnDisposition.ADVISORY_RESPONSE,
                reason_code="semantic_advisory_response",
                semantic_route="semantic_advisory_response",
                session_id=request.session_id,
                turn_id=request.turn_id,
                turn_sequence=request.turn_sequence,
                answer=adaptive_answer.answer,
                adaptive_answer=adaptive_answer,
            ),
            model_extensions,
        )
    if result.disposition == "direct_response":
        intent = result.planning.direct_response_intent
        answer = result.planning.direct_response_answer
        if not isinstance(intent, SemanticDirectResponseIntent) or not isinstance(answer, str):
            return _terminal_result(
                request,
                "held",
                "semantic_runtime_failed",
            ), model_extensions
        return (
            ContractSemanticTurnResult(
                disposition=SemanticTurnDisposition.DIRECT_RESPONSE,
                reason_code="semantic_direct_response",
                semantic_route="semantic_direct_response",
                session_id=request.session_id,
                turn_id=request.turn_id,
                turn_sequence=request.turn_sequence,
                answer=answer,
                direct_response_intent=intent,
            ),
            model_extensions,
        )
    if result.disposition != "answered":
        execution_hold = _project_execution_hold(request, result)
        if execution_hold is not None:
            continuation = (
                _project_investigation_continuation(
                    request,
                    result,
                    execution_receipt_digest=_execution_receipt_digest(result.execution),
                )
                if result.execution is not None
                else None
            )
            operational_extensions = (
                _SemanticProjectionExtensions(investigation_continuation=continuation)
                if continuation is not None
                else None
            )
            return execution_hold, _merge_projection_extensions(
                model_extensions,
                operational_extensions,
            )
        reason_codes = {
            "clarification": "semantic_clarification_required",
            "held": "semantic_evidence_held",
            "unsupported": "semantic_request_unsupported",
            "action_draft": "semantic_action_draft",
            "cancelled": "semantic_request_cancelled",
        }
        reason_code = (
            result.reason
            if result.disposition == "held"
            and result.reason
            in (_AUTHORITATIVE_EVIDENCE_UNAVAILABLE_REASONS | _SEMANTIC_PLANNER_UNAVAILABLE_REASONS)
            else reason_codes.get(result.disposition, "semantic_runtime_failed")
        )
        disposition = result.disposition if result.disposition in reason_codes else "held"
        answer = result.planning.clarification if result.disposition == "clarification" else None
        terminal = _terminal_result(
            request,
            disposition,
            reason_code,
            answer=answer,
            assurance_observation=project_semantic_assurance(
                result,
                disposition=disposition,
            ),
        )
        if disposition == "action_draft" and result.adaptive_answer is not None:
            terminal = ContractSemanticTurnResult.model_validate(
                {**terminal.model_dump(), "adaptive_answer": result.adaptive_answer}
            )
        continuation = None
        if result.disposition == "held" and result.execution is not None:
            continuation = _project_investigation_continuation(
                request,
                result,
                execution_receipt_digest=_execution_receipt_digest(result.execution),
            )
        operational_extensions = (
            _SemanticProjectionExtensions(investigation_continuation=continuation)
            if continuation is not None
            else None
        )
        return terminal, _merge_projection_extensions(
            model_extensions,
            operational_extensions,
        )

    planning = result.planning
    plan = planning.plan
    frame = planning.frame
    execution = result.execution
    if execution is not None:
        _authority, authority_status = resolve_execution_authority(
            execution,
            frame=frame,
            plan=plan,
        )
        if authority_status != "verified":
            reason = (
                "semantic_evidence_authority_conflict"
                if authority_status == "conflict"
                else "semantic_evidence_authority_missing"
            )
            authority_hold = _project_execution_hold(
                request,
                replace(result, disposition="held", reason=reason),
            )
            if authority_hold is not None:
                return authority_hold, model_extensions
    verified_plan_failure = _verified_plan_failure(result, plan, execution)
    if verified_plan_failure is not None or frame is None or plan is None or execution is None:
        return _evidence_incomplete(
            request,
            verified_plan_failure or "plan_missing",
            result=result,
        ), model_extensions
    evidence_refs = tuple(
        dict.fromkeys(
            evidence_ref for receipt in execution.receipts for evidence_ref in receipt.evidence_refs
        )
    )
    if not evidence_refs:
        return _evidence_incomplete(request, "no_evidence_refs", result=result), model_extensions
    if len(evidence_refs) > MAX_SEMANTIC_EVIDENCE_REFS:
        return _evidence_incomplete(
            request,
            "too_many_evidence_refs",
            result=result,
        ), model_extensions
    execution_receipt_digest = _execution_receipt_digest(execution)
    investigation_continuation = _project_investigation_continuation(
        request,
        result,
        execution_receipt_digest=execution_receipt_digest,
    )
    checks_total = len(execution.receipts)
    checks_completed = sum(receipt.status is TaskStatus.COMPLETED for receipt in execution.receipts)
    rule_search_found, rule_search, rule_search_node_id = _project_rule_search(result, execution)
    if rule_search_found and rule_search is None:
        return _evidence_incomplete(
            request,
            "rule_search_projection_rejected",
            result=result,
        ), model_extensions
    incident_found, incident_evidence, incident_node_id = _project_incident_evidence(
        result,
        execution,
    )
    if incident_found and incident_evidence is None:
        return _evidence_incomplete(
            request,
            "incident_evidence_projection_rejected",
            result=result,
        ), model_extensions
    unsatisfied_binding = _unsatisfied_incident_binding(request, incident_evidence)
    if unsatisfied_binding is not None:
        return _terminal_result(
            request,
            "held",
            unsatisfied_binding,
            answer=_incident_binding_hold_answer(request.locale),
        ), model_extensions
    relationships_found, relationships, relationships_node_id = project_ontology_relationships(
        result,
        execution,
    )
    if relationships_found and relationships is None:
        return _evidence_incomplete(
            request,
            "relationship_projection_rejected",
            result=result,
        ), model_extensions
    evidence_requirements = tuple(getattr(frame, "evidence_requirements", ()))
    optional_document_node_ids = (
        tuple(
            node.node_id
            for node in getattr(plan, "nodes", ())
            if node.kind is QueryNodeKind.FUNCTION
            and node.arguments.get("function_name") == "query.governed_documents"
        )
        if "governed_documents.optional" in evidence_requirements
        else ()
    )
    answer, technical_details = _render_query_answer(
        request,
        execution,
        operation=frame.operation.value,
        output_shape=frame.output_shape,
        subject_constraints=tuple(frame.subject_constraints),
        measure_concepts=tuple(frame.measure_concepts),
        evidence_requirements=evidence_requirements,
        rule_search=rule_search,
        rule_search_node_id=rule_search_node_id,
        incident_evidence=incident_evidence,
        incident_node_id=incident_node_id,
        ontology_relationships=relationships,
        ontology_relationships_node_id=relationships_node_id,
        optional_document_node_ids=optional_document_node_ids,
    )
    if answer is None or technical_details is None:
        return _evidence_incomplete(
            request,
            "answer_rendering_rejected",
            result=result,
        ), model_extensions
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition.ANSWERED,
        reason_code=(
            "semantic_answer_partial"
            if optional_document_evidence_degraded(planning, execution)
            else "semantic_answer_verified"
        ),
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
        checks_completed=checks_completed,
        checks_total=checks_total,
        answer=answer,
        assurance_observation=project_semantic_assurance(
            result,
            disposition="answered",
        ),
    ), _merge_projection_extensions(
        model_extensions,
        _SemanticProjectionExtensions(
            rule_search=rule_search,
            technical_details=technical_details,
            investigation_continuation=investigation_continuation,
        ),
    )


def _project_investigation_continuation(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
    *,
    execution_receipt_digest: str,
) -> SemanticInvestigationContinuation | None:
    """Project one exact S3 recovery anchor without retaining operator prose."""

    planning = result.planning
    intent = getattr(planning, "investigation_intent", None)
    plan = getattr(planning, "plan", None)
    frame = getattr(planning, "frame", None)
    if intent is None or plan is None or frame is None:
        return None
    targets = tuple(
        entity
        for entity in intent.entities
        if entity.role is InvestigationEntityRole.AFFECTED_TARGET
    )
    primary = next(
        (
            measure
            for measure in intent.symptom_measures
            if measure.measure_id == intent.primary_symptom_measure_id
        ),
        None,
    )
    cause_measures = {hypothesis.cause_measure_concept for hypothesis in intent.hypotheses}
    if (
        len(targets) != 1
        or targets[0].object_type_candidates != ("BusinessService",)
        or primary is None
        or primary.concept_id != "service.latency"
        or "dependency.latency" not in cause_measures
    ):
        return None
    nodes = {node.node_id: node for node in plan.nodes}
    baseline = nodes.get("symptom-baseline")
    current = nodes.get("symptom-current")
    if baseline is None or current is None:
        return None
    baseline_start = _argument_datetime(baseline.arguments, "start")
    baseline_end = _argument_datetime(baseline.arguments, "end")
    observation_cutoff = _argument_datetime(current.arguments, "end")
    frame_digest = getattr(frame, "frame_digest", None)
    manifest_digest = planning.manifest_digest
    if not isinstance(frame_digest, str) or not isinstance(manifest_digest, str):
        return None
    return SemanticInvestigationContinuation(
        source_session_id=request.session_id,
        source_turn_id=request.turn_id,
        source_turn_sequence=request.turn_sequence,
        target_type="BusinessService",
        target_value=targets[0].span.text,
        recovery_measure_concepts=("dependency.latency", "service.latency"),
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        initial_observation_cutoff=observation_cutoff,
        ontology_release_digest=plan.ontology_release_digest,
        principal_manifest_digest=manifest_digest,
        source_frame_digest=frame_digest,
        source_plan_digest=plan.plan_digest,
        source_execution_receipt_digest=execution_receipt_digest,
        execution_authority=False,
    )


def _execution_receipt_digest(execution: QueryPlanExecution) -> str:
    return content_digest(
        {
            "plan_digest": execution.plan_digest,
            "status": execution.status,
            "output_node_ids": execution.output_node_ids,
            "receipts": [receipt.model_dump(mode="json") for receipt in execution.receipts],
        }
    )


def _argument_datetime(arguments: Mapping[str, object], field: str) -> datetime:
    value = arguments.get(field)
    if not isinstance(value, str):
        raise ValueError(f"investigation continuation {field} is unavailable")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _aware_utc(parsed, field=f"investigation continuation {field}")


def _semantic_turn_timing(
    *,
    envelope: Mapping[str, object],
    result: ContractSemanticTurnResult,
    completed_at: datetime,
) -> dict[str, object]:
    """Partition the request-to-projection interval into contiguous observed phases."""

    requested_at_raw = envelope.get("requested_at")
    if not isinstance(requested_at_raw, str):
        raise ValueError("semantic request timestamp is unavailable")
    requested_at = _aware_utc(
        datetime.fromisoformat(requested_at_raw.replace("Z", "+00:00")),
        field="semantic requested_at",
    )
    requested_at = requested_at.replace(
        microsecond=(requested_at.microsecond // 1000) * 1000,
    )
    if completed_at < requested_at:
        requested_at = completed_at

    evidence_bounds = _semantic_evidence_bounds(result.intent_graph_evidence)
    phases: list[dict[str, object]] = []
    if evidence_bounds is None:
        phases.append(
            _semantic_timing_phase(
                "semantic_plan",
                requested_at,
                completed_at,
                status="completed",
            )
        )
    else:
        evidence_start, evidence_end, evidence_completed = evidence_bounds
        evidence_start = min(max(evidence_start, requested_at), completed_at)
        evidence_end = min(max(evidence_end, evidence_start), completed_at)
        phases.extend(
            (
                _semantic_timing_phase(
                    "semantic_plan",
                    requested_at,
                    evidence_start,
                    status="completed",
                ),
                _semantic_timing_phase(
                    "evidence",
                    evidence_start,
                    evidence_end,
                    status="completed" if evidence_completed else "degraded",
                ),
                _semantic_timing_phase(
                    "generation",
                    evidence_end,
                    completed_at,
                    status="completed" if result.answer else "degraded",
                ),
            )
        )
    return {
        "schema_version": 1,
        "started_at": requested_at.isoformat(timespec="milliseconds"),
        "completed_at": completed_at.isoformat(timespec="milliseconds"),
        "duration_ms": _elapsed_milliseconds(requested_at, completed_at),
        "phases": phases,
    }


def _semantic_evidence_bounds(
    evidence: Mapping[str, object] | None,
) -> tuple[datetime, datetime, bool] | None:
    if not isinstance(evidence, Mapping):
        return None
    goals = evidence.get("goals")
    if not isinstance(goals, list) or not goals:
        return None
    intervals: list[tuple[datetime, datetime]] = []
    completed = True
    for goal in goals:
        if not isinstance(goal, Mapping):
            return None
        started_at = goal.get("started_at")
        completed_at = goal.get("completed_at")
        if not isinstance(started_at, str) or not isinstance(completed_at, str):
            return None
        start = _aware_utc(
            datetime.fromisoformat(started_at.replace("Z", "+00:00")),
            field="semantic evidence started_at",
        )
        end = _aware_utc(
            datetime.fromisoformat(completed_at.replace("Z", "+00:00")),
            field="semantic evidence completed_at",
        )
        if end < start:
            return None
        intervals.append(
            (
                start.replace(microsecond=(start.microsecond // 1000) * 1000),
                end.replace(microsecond=(end.microsecond // 1000) * 1000),
            )
        )
        completed = completed and goal.get("status") == "completed"
    return (
        min(start for start, _end in intervals),
        max(end for _start, end in intervals),
        completed,
    )


def _semantic_timing_phase(
    phase: str,
    started_at: datetime,
    completed_at: datetime,
    *,
    status: str,
) -> dict[str, object]:
    return {
        "phase": phase,
        "status": status,
        "started_at": started_at.isoformat(timespec="milliseconds"),
        "completed_at": completed_at.isoformat(timespec="milliseconds"),
        "duration_ms": _elapsed_milliseconds(started_at, completed_at),
    }


def _elapsed_milliseconds(started_at: datetime, completed_at: datetime) -> int:
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _semantic_model_extensions(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
) -> _SemanticProjectionExtensions | None:
    observations = getattr(result.planning, "model_observations", ())
    social_act = getattr(result.planning, "social_act", None)
    social_act_value = getattr(social_act, "value", None)
    if not observations and not isinstance(social_act_value, str):
        return None
    if not observations:
        return _SemanticProjectionExtensions(social_act=social_act_value)
    usage_keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    usage = {
        key: sum(
            observation.usage.get(key, 0)
            for observation in observations
            if observation.usage is not None
        )
        for key in usage_keys
    }
    measured_usage = (
        usage if any(observation.usage is not None for observation in observations) else None
    )
    calls: list[dict[str, object]] = []
    latency_ms = 0
    for index, observation in enumerate(observations, start=1):
        call = dict(observation.trace_call)
        kind = call.get("kind")
        call["call_id"] = (
            f"{kind}-{index}" if isinstance(kind, str) and kind else f"semantic-model-{index}"
        )
        duration = call.get("duration_ms")
        if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0:
            latency_ms += duration
        calls.append(call)
    return _SemanticProjectionExtensions(
        model=observations[-1].model,
        latency_ms=latency_ms,
        usage=measured_usage,
        model_trace=(
            {
                "schema_version": 1,
                "redacted": True,
                "calls": calls,
                "omitted_calls": 0,
            }
            if request.include_model_trace
            else None
        ),
        social_act=social_act_value if isinstance(social_act_value, str) else None,
    )


def _merge_projection_extensions(
    first: _SemanticProjectionExtensions | None,
    second: _SemanticProjectionExtensions | None,
) -> _SemanticProjectionExtensions | None:
    if first is None:
        return second
    if second is None:
        return first
    return _SemanticProjectionExtensions(
        rule_search=first.rule_search if first.rule_search is not None else second.rule_search,
        technical_details=(
            first.technical_details
            if first.technical_details is not None
            else second.technical_details
        ),
        model=first.model if first.model is not None else second.model,
        latency_ms=first.latency_ms if first.latency_ms is not None else second.latency_ms,
        usage=first.usage if first.usage is not None else second.usage,
        model_trace=first.model_trace if first.model_trace is not None else second.model_trace,
        social_act=first.social_act if first.social_act is not None else second.social_act,
        investigation_continuation=(
            first.investigation_continuation
            if first.investigation_continuation is not None
            else second.investigation_continuation
        ),
        operational_evidence=(
            first.operational_evidence
            if first.operational_evidence is not None
            else second.operational_evidence
        ),
    )


def _project_execution_hold(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
) -> ContractSemanticTurnResult | None:
    """Retain verified read attempts when execution, not planning, caused the hold."""
    planning = result.planning
    plan = planning.plan
    execution = result.execution
    graph = result.intent_graph
    evidence = result.intent_graph_evidence
    if (
        result.disposition != "held"
        or plan is None
        or execution is None
        or not isinstance(graph, dict)
        or not isinstance(evidence, dict)
        or planning.manifest_digest is None
        or planning.manifest_digest != plan.semantic_catalog_digest
        or execution.plan_digest != plan.plan_digest
        or (
            execution.status == "completed"
            and result.reason
            not in {
                "semantic_current_relationship_mapping_unavailable",
                "semantic_evidence_authority_conflict",
                "semantic_evidence_authority_missing",
            }
        )
        or not execution.receipts
        or not _projected_execution_evidence_matches(result, execution)
    ):
        return None
    evidence_refs = tuple(
        dict.fromkeys(ref for receipt in execution.receipts for ref in receipt.evidence_refs)
    )[:MAX_SEMANTIC_EVIDENCE_REFS]
    execution_receipt_digest = content_digest(
        {
            "plan_digest": execution.plan_digest,
            "status": execution.status,
            "output_node_ids": execution.output_node_ids,
            "receipts": [receipt.model_dump(mode="json") for receipt in execution.receipts],
        }
    )
    completed = sum(receipt.status is TaskStatus.COMPLETED for receipt in execution.receipts)
    return ContractSemanticTurnResult(
        disposition=SemanticTurnDisposition.HELD,
        reason_code=(
            result.reason
            if result.reason
            in {
                "semantic_current_relationship_mapping_unavailable",
                "semantic_evidence_authority_conflict",
                "semantic_evidence_authority_missing",
            }
            else "semantic_evidence_held"
        ),
        unavailable_reason="authoritative_evidence_unavailable",
        session_id=request.session_id,
        turn_id=request.turn_id,
        turn_sequence=request.turn_sequence,
        ontology_release_digest=plan.ontology_release_digest,
        principal_manifest_digest=planning.manifest_digest,
        plan_digest=plan.plan_digest,
        execution_receipt_digest=execution_receipt_digest,
        intent_graph=graph,
        intent_graph_evidence=evidence,
        evidence_refs=evidence_refs,
        checks_completed=completed,
        checks_total=len(execution.receipts),
        answer=_render_execution_hold_answer(request, result, execution),
        assurance_observation=project_semantic_assurance(
            result,
            disposition="held",
        ),
    )


def _projected_execution_evidence_matches(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> bool:
    graph = result.intent_graph
    evidence = result.intent_graph_evidence
    if not isinstance(graph, dict) or not isinstance(evidence, dict):
        return False
    graph_goals = graph.get("goals")
    evidence_goals = evidence.get("goals")
    evidence_status = evidence.get("status")
    status_is_projectable = evidence_status in {
        "partial",
        "unavailable",
        "failed",
        "cancelled",
    } or (
        result.reason == "semantic_current_relationship_mapping_unavailable"
        and evidence_status == "completed"
    )
    if (
        graph.get("schema_version") != 2
        or graph.get("action_posture") != "advise_only"
        or evidence.get("schema_version") not in {1, 2}
        or not status_is_projectable
        or not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not 1 <= len(graph_goals) <= MAX_INTENT_GRAPH_GOALS
        or len(graph_goals) != len(evidence_goals)
        or len(evidence_goals) != len(execution.receipts)
    ):
        return False
    for graph_goal, evidence_goal, receipt in zip(
        graph_goals,
        evidence_goals,
        execution.receipts,
        strict=True,
    ):
        if not isinstance(graph_goal, dict) or not isinstance(evidence_goal, dict):
            return False
        refs = evidence_goal.get("evidence_refs", [])
        if (
            evidence_goal.get("goal_id") != graph_goal.get("goal_id")
            or evidence_goal.get("intent") != graph_goal.get("intent")
            or evidence_goal.get("capability") != graph_goal.get("capability")
            or evidence_goal.get("task_id") != receipt.task_id
            or evidence_goal.get("status") != receipt.status.value
            or evidence_goal.get("reason") != receipt.reason
            or evidence_goal.get("authority")
            != (receipt.authority.value if receipt.authority is not None else None)
            or not isinstance(refs, list)
            or tuple(refs) != receipt.evidence_refs
        ):
            return False
    return True


def _render_execution_hold_answer(
    request: SemanticTurnRequest,
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
) -> str:
    korean = request.locale.casefold().startswith("ko")
    limitations = []
    for receipt in execution.receipts:
        capability = receipt.capability or receipt.intent
        if receipt.reason is not None:
            limitations.append(f"`{capability}`: `{receipt.reason}`")
    causal_answer = _render_partial_causal_answer(
        result,
        execution,
        korean=korean,
        additional_limitations=limitations,
    )
    if causal_answer is not None:
        return causal_answer
    hypotheses = _held_hypothesis_lines(result, korean=korean)
    if korean:
        return "\n".join(
            [
                "## 확인 불가",
                "",
                "현재 authoritative evidence로는 요청한 결론을 결정할 수 없습니다.",
                "",
                "## 확인 가능한 범위",
                "",
                "- 완료된 단계와 근거 참조만 관측 사실로 사용할 수 있습니다.",
                "- 완료되지 않은 가설은 `supported` 또는 `refuted`로 승격하지 않고 "
                "`unresolved`로 유지합니다.",
                *(["", "## 가설 상태", "", *hypotheses] if hypotheses else []),
                "",
                "## 제한 사항",
                "",
                *(
                    [f"- {item}" for item in limitations]
                    or ["- 필요한 authoritative evidence가 완전하지 않습니다."]
                ),
                "",
                "## 다음 안전 단계",
                "",
                "권한, provider 가용성, source completeness를 확인한 뒤 같은 대상과 시간 "
                "범위에서 읽기 전용으로 다시 관측하세요.",
                "",
                "`execution_authority=false`",
            ]
        )
    return "\n".join(
        [
            "## Unable to determine",
            "",
            "The requested conclusion cannot be determined from the current "
            "authoritative evidence.",
            "",
            "## Supported scope",
            "",
            "- Only completed steps and their evidence references can support observations.",
            "- Incomplete hypotheses remain `unresolved`; they are not promoted to "
            "`supported` or `refuted`.",
            *(["", "## Hypothesis status", "", *hypotheses] if hypotheses else []),
            "",
            "## Limitations",
            "",
            *(
                [f"- {item}" for item in limitations]
                or ["- Required authoritative evidence is incomplete."]
            ),
            "",
            "## Next safe step",
            "",
            "Verify authorization, provider availability, and source completeness, then observe "
            "the same target and time bounds again through the read-only path.",
            "",
            "`execution_authority=false`",
        ]
    )


def _held_hypothesis_lines(
    result: RuntimeSemanticTurnResult,
    *,
    korean: bool,
) -> list[str]:
    intent = getattr(result.planning, "investigation_intent", None)
    raw_hypotheses = getattr(intent, "hypotheses", ())
    if not isinstance(raw_hypotheses, tuple):
        return []
    lines: list[str] = []
    for hypothesis in raw_hypotheses:
        hypothesis_id = getattr(hypothesis, "hypothesis_id", None)
        if isinstance(hypothesis_id, str) and hypothesis_id:
            lines.append(
                f"- `{hypothesis_id}` - `unresolved`"
                + (" - 근거 미완료" if korean else " - evidence incomplete")
            )
    return lines


def _render_partial_causal_answer(
    result: RuntimeSemanticTurnResult,
    execution: QueryPlanExecution,
    *,
    korean: bool,
    additional_limitations: Sequence[str],
) -> str | None:
    outputs: list[dict[str, object]] = []
    for node_id in execution.output_node_ids:
        node_result = execution.results.get(node_id)
        if node_result is None:
            continue
        extension_output = _typed_extension_answer_output(node_id, node_result.value)
        if extension_output is not None:
            extension_output["evidence_refs"] = list(node_result.evidence_refs)
            outputs.append(extension_output)
            continue
        if not isinstance(node_result.value, QueryTable):
            continue
        table = node_result.value
        rows: list[dict[str, object]] = [
            {"row_id": row.row_id, "values": row.values} for row in table.rows[:20]
        ]
        output = _answer_output(
            node_id=node_id,
            table=table,
            rows=rows,
            evidence_refs=node_result.evidence_refs,
        )
        outputs.append(output)
    if not any(output.get("result_kind") == "causal.join" for output in outputs):
        outputs.extend(_unresolved_hypothesis_outputs(result))
    return _render_causal_query_answer(
        outputs,
        korean=korean,
        additional_limitations=additional_limitations,
    )


def _unresolved_hypothesis_outputs(
    result: RuntimeSemanticTurnResult,
) -> list[dict[str, object]]:
    intent = getattr(result.planning, "investigation_intent", None)
    raw_hypotheses = getattr(intent, "hypotheses", ())
    if not isinstance(raw_hypotheses, tuple):
        return []
    outputs: list[dict[str, object]] = []
    for hypothesis in raw_hypotheses:
        hypothesis_id = getattr(hypothesis, "hypothesis_id", None)
        if isinstance(hypothesis_id, str) and hypothesis_id:
            outputs.append(
                {
                    "node_id": f"hypothesis-{hypothesis_id}",
                    "result_kind": "causal.join",
                    "evidence_refs": [],
                    "summary": {
                        "hypothesis_id": hypothesis_id,
                        "status": "unresolved",
                        "limitations": ["evidence_not_completed"],
                        "temporal_claim": None,
                    },
                }
            )
    return outputs


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
    optional_document_degraded = optional_document_evidence_degraded(planning, execution)
    if execution.status != "completed" and not optional_document_degraded:
        return "execution_not_completed"
    if not execution.receipts:
        return "no_receipts"
    if not optional_document_degraded and any(
        receipt.status is not TaskStatus.COMPLETED for receipt in execution.receipts
    ):
        return "receipt_not_completed"
    if not _projected_answer_evidence_is_complete(result, execution):
        return "intent_graph_evidence_mismatch"
    return None


def _evidence_incomplete(
    request: SemanticTurnRequest,
    failure_type: str,
    *,
    result: RuntimeSemanticTurnResult | None = None,
) -> ContractSemanticTurnResult:
    _LOGGER.warning("semantic_turn_evidence_incomplete", extra={"failure_type": failure_type})
    return _terminal_result(
        request,
        "held",
        "semantic_evidence_incomplete",
        assurance_observation=(
            project_semantic_assurance(result, disposition="held") if result is not None else None
        ),
    )


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
    optional_document_degraded = optional_document_evidence_degraded(
        result.planning,
        execution,
    )
    expected_status = "partial" if optional_document_degraded else "completed"
    expected_mode = "partial" if optional_document_degraded else None
    if (
        graph.get("schema_version") != 2
        or graph.get("action_posture") != "advise_only"
        or evidence.get("schema_version") not in {1, 2}
        or evidence.get("status") != expected_status
        or (expected_mode is not None and evidence.get("evidence_mode") != expected_mode)
        or (
            expected_mode is None
            and evidence.get("evidence_mode")
            not in {"operational_grounded", "document_grounded", "mixed_grounded"}
        )
        or not isinstance(graph_goals, list)
        or not isinstance(evidence_goals, list)
        or not 1 <= len(graph_goals) <= MAX_INTENT_GRAPH_GOALS
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
            or evidence_goal.get("status") != receipt.status.value
            or evidence_goal.get("authority")
            != (receipt.authority.value if receipt.authority is not None else None)
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
    assurance_observation: SemanticAssuranceObservation | None = None,
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
        assurance_observation=assurance_observation,
    )


def _render_query_answer(
    request: SemanticTurnRequest,
    execution: QueryPlanExecution,
    *,
    operation: str,
    output_shape: str,
    subject_constraints: tuple[str, ...] = (),
    measure_concepts: tuple[str, ...] = (),
    evidence_requirements: tuple[str, ...] = (),
    rule_search: RuleSearchProjection | None = None,
    rule_search_node_id: str | None = None,
    incident_evidence: dict[str, object] | None = None,
    incident_node_id: str | None = None,
    ontology_relationships: dict[str, object] | None = None,
    ontology_relationships_node_id: tuple[str, ...] | None = None,
    optional_document_node_ids: tuple[str, ...] = (),
) -> tuple[str | None, dict[str, object] | None]:
    outputs: list[dict[str, object]] = []
    projected_rule_search = False
    projected_incident = False
    projected_relationships = False
    relationship_node_ids = set(ontology_relationships_node_id or ())
    for node_id in execution.output_node_ids:
        result = execution.results.get(node_id)
        if result is None:
            if (
                node_id in optional_document_node_ids
                and "governed_documents.optional" in evidence_requirements
            ):
                continue
            return None, None
        if isinstance(result.value, dict):
            if incident_evidence is not None and node_id == incident_node_id:
                if projected_incident:
                    return None, None
                outputs.append(
                    {
                        **_incident_answer_output(
                            node_id=node_id,
                            incident_evidence=incident_evidence,
                        ),
                        "evidence_refs": list(result.evidence_refs),
                    }
                )
                projected_incident = True
            elif ontology_relationships is not None and node_id in relationship_node_ids:
                if projected_relationships:
                    continue
                relationship_evidence_refs = tuple(
                    evidence_ref
                    for relationship_node_id in ontology_relationships_node_id or ()
                    if (relationship_result := execution.results.get(relationship_node_id))
                    is not None
                    for evidence_ref in relationship_result.evidence_refs
                )
                outputs.append(
                    {
                        "node_id": node_id,
                        "ontology_relationships": ontology_relationships,
                        "evidence_refs": list(dict.fromkeys(relationship_evidence_refs)),
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
                        "evidence_refs": list(result.evidence_refs),
                    }
                )
                projected_rule_search = True
            else:
                return None, None
            continue
        extension_output = _typed_extension_answer_output(node_id, result.value)
        if extension_output is not None:
            extension_output["evidence_refs"] = list(result.evidence_refs)
            outputs.append(extension_output)
            continue
        if not isinstance(result.value, QueryTable):
            return None, None
        table = result.value
        rows: list[dict[str, object]] = []
        if len(table.rows) <= 40:
            projected_rows = table.rows
        else:
            projected_rows = (
                table.rows[-20:] if output_shape == "resource_event_history" else table.rows[:20]
            )
        for row in projected_rows:
            candidate_rows: list[dict[str, object]] = [
                *rows,
                {"row_id": row.row_id, "values": _answer_row_values(row.values)},
            ]
            candidate = [
                *outputs,
                _answer_output(
                    node_id=node_id,
                    table=table,
                    rows=candidate_rows,
                    evidence_refs=result.evidence_refs,
                ),
            ]
            if len(_answer_json(candidate).encode("utf-8")) > 48_000:
                break
            rows = candidate_rows
        outputs.append(
            _answer_output(
                node_id=node_id,
                table=table,
                rows=rows,
                evidence_refs=result.evidence_refs,
            )
        )
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
            **({"measure_concepts": list(measure_concepts)} if measure_concepts else {}),
            **(
                {"evidence_requirements": list(evidence_requirements)}
                if evidence_requirements
                else {}
            ),
            **(
                {"presentation_semantics": presentation_semantics}
                if (
                    presentation_semantics := project_presentation_semantics(
                        operation=operation,
                        output_shape=output_shape,
                        outputs=outputs,
                    )
                )
                is not None
                else {}
            ),
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
            else _render_general_query_answer(
                request,
                outputs,
                output_shape=output_shape,
                subject_constraints=subject_constraints,
                measure_concepts=measure_concepts,
                evidence_requirements=evidence_requirements,
            )
        )
    )
    return (answer, technical_details) if len(answer) <= 64_000 else (None, None)


_ANSWER_ROW_LIFTED_FIELDS = (
    "name",
    "revision_name",
    "ready_revision_name",
    "running_status",
    "source_observed_at",
    "inventory_read_at",
    "provisioning_status",
    "type",
    "status",
    "location",
)
_SENSITIVE_ANSWER_FIELDS = frozenset(
    {
        "access_token",
        "authorization",
        "client_secret",
        "credential",
        "password",
        "resource_id",
        "subscription_id",
        "tenant_id",
        "token",
    }
)
_SENSITIVE_ANSWER_VALUE_MARKERS = (
    "http://",
    "https://",
    "bearer ",
    "/subscriptions/",
)
_REDACTED_ANSWER_VALUE = "<redacted>"


def _answer_row_values(values: Mapping[str, object]) -> dict[str, object]:
    """Keep bounded scalar answer fields and exclude nested provider payloads."""
    projected = {
        field: _redact_answer_scalar(field, value)
        for field, value in values.items()
        if isinstance(field, str) and field and not isinstance(value, Mapping | list)
    }
    if values.get("record_kind") == "excerpt" and isinstance(values.get("text"), str):
        original_text = values["text"]
        displayed_text = _redact_answer_scalar("text", original_text)
        projected["text"] = displayed_text
        rendered_text, _display_truncated = _bounded_document_text(
            str(displayed_text),
            maximum=1_200,
        )
        projected["display_content_digest"] = content_digest({"text": rendered_text})
        projected["redaction_applied"] = displayed_text != original_text
    current: list[Mapping[str, object]] = [values]
    for _depth in range(2):
        nested = [
            value for item in current for value in item.values() if isinstance(value, Mapping)
        ]
        for item in nested:
            for field in _ANSWER_ROW_LIFTED_FIELDS:
                value = item.get(field)
                if value is not None and not isinstance(value, Mapping | list):
                    projected.setdefault(field, _redact_answer_scalar(field, value))
        current = nested
    return projected


def _redact_answer_scalar(field: str, value: object) -> object:
    if not isinstance(value, str):
        return value
    folded_field = field.casefold()
    folded_value = value.casefold()
    if (
        folded_field in _SENSITIVE_ANSWER_FIELDS
        or folded_field.endswith(("_token", "_secret", "_credential"))
        or any(marker in folded_value for marker in _SENSITIVE_ANSWER_VALUE_MARKERS)
    ):
        return _REDACTED_ANSWER_VALUE
    return value


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
            "operation": "action_draft",
            "semantic_operation": "action_draft",
            "candidate": "collect_evidence",
            "authority": "candidate_only",
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
            "## 제한 사항\n\n"
            f"- 누락된 근거: {missing}\n\n"
            "## 다음 안전 단계\n\n"
            "- ACTION_DRAFT 후보: "
            f"{_incident_next_step_text(gap_values, korean=True, root_cause=root_cause)}\n\n"
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
        "## Limitations\n\n"
        f"- Missing evidence: {missing}\n\n"
        "## Next safe step\n\n"
        "- Candidate ACTION_DRAFT: "
        f"{_incident_next_step_text(gap_values, korean=False, root_cause=root_cause)}\n\n"
        "This result is read-only and grants no execution authority."
    )


def _render_general_query_answer(
    request: SemanticTurnRequest,
    outputs: list[dict[str, object]],
    *,
    output_shape: str | None = None,
    subject_constraints: tuple[str, ...] = (),
    measure_concepts: tuple[str, ...] = (),
    evidence_requirements: tuple[str, ...] = (),
) -> str:
    """Report what was verified without naming the plan that produced it.

    A plan node id and the words that describe the query engine are internal
    vocabulary. The operator asked a question, so the answer states what the
    result contains and leaves the machinery in technical details.
    """
    korean = request.locale.casefold().startswith("ko")
    document_section = _render_governed_document_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if document_section is not None:
        if output_shape == "governed_document_excerpts":
            return document_section
        operational_outputs = [
            output for output in outputs if not _is_governed_document_output(output)
        ]
        if operational_outputs:
            operational_answer = _render_general_query_answer(
                request,
                operational_outputs,
                output_shape=output_shape,
                subject_constraints=subject_constraints,
                measure_concepts=measure_concepts,
                evidence_requirements=(),
            )
            return f"{operational_answer}\n\n{document_section}"
    elif any(requirement == "governed_documents.optional" for requirement in evidence_requirements):
        unavailable = (
            "## 문서 근거 범위\n\n"
            "관리되는 문서 검색 기능을 사용할 수 없어 다른 검증된 근거만 사용했습니다."
            if korean
            else (
                "## Document evidence coverage\n\n"
                "Governed document retrieval was unavailable, so this answer uses only "
                "the other verified evidence."
            )
        )
        operational_answer = _render_general_query_answer(
            request,
            outputs,
            output_shape=output_shape,
            subject_constraints=subject_constraints,
            measure_concepts=measure_concepts,
            evidence_requirements=(),
        )
        return f"{operational_answer}\n\n{unavailable}"
    target_candidates_answer = _render_target_candidates_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if target_candidates_answer is not None:
        return target_candidates_answer
    resource_event_answer = _render_resource_event_history_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if resource_event_answer is not None:
        return resource_event_answer
    state_transition_answer = _render_state_transition_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if state_transition_answer is not None:
        return state_transition_answer
    resource_condition_answer = _render_resource_condition_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
        measure_concepts=measure_concepts,
    )
    if resource_condition_answer is not None:
        return resource_condition_answer
    subscription_scope_answer = _render_subscription_scope_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if subscription_scope_answer is not None:
        return subscription_scope_answer
    service_health_answer = _render_service_health_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
        measure_concepts=measure_concepts,
    )
    if service_health_answer is not None:
        return service_health_answer
    causal_answer = _render_causal_query_answer(outputs, korean=korean)
    if causal_answer is not None:
        return causal_answer
    correlation_answer = _render_error_activity_correlation_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if correlation_answer is not None:
        return correlation_answer
    health_answer = _render_health_query_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if health_answer is not None:
        return health_answer
    current_state_answer = _render_current_state_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if current_state_answer is not None:
        return current_state_answer
    declaration_count_answer = _render_ontology_declaration_count_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
        subject_constraints=subject_constraints,
    )
    if declaration_count_answer is not None:
        return declaration_count_answer
    impact_answer = _render_impact_query_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if impact_answer is not None:
        return impact_answer
    empty_answer = _render_generic_empty_query_answer(
        outputs,
        korean=korean,
        output_shape=output_shape,
    )
    if empty_answer is not None:
        return empty_answer
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
        if (
            not isinstance(returned, int)
            or isinstance(returned, bool)
            or not isinstance(total, int)
            or isinstance(total, bool)
            or total < returned
        ):
            lines.append(
                "- 행 개수 메타데이터를 검증할 수 없습니다."
                if korean
                else "- Row-count metadata could not be verified."
            )
        elif returned == 0 and total == 0:
            lines.append(
                "- 하나의 검증된 출력에서 일치하는 행이 반환되지 않았습니다."
                if korean
                else "- One verified output returned no matching rows."
            )
        else:
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


def _render_governed_document_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    document_outputs = [output for output in outputs if _is_governed_document_output(output)]
    if not document_outputs:
        return None
    if len(document_outputs) != 1:
        return (
            "## 문서 근거를 검증할 수 없음\n\n문서 검색 출력이 하나보다 많아 답변을 보류했습니다."
            if korean
            else (
                "## Document evidence could not be verified\n\n"
                "More than one document retrieval output was returned."
            )
        )
    document_output = document_outputs[0]
    rows = document_output.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    source_complete = document_output.get("source_complete")
    source_limitation = document_output.get("source_truncation_reason")
    projection_truncated = document_output.get("display_truncated")
    if (
        not isinstance(source_complete, bool)
        or not isinstance(projection_truncated, bool)
        or (
            not source_complete
            and (
                not isinstance(source_limitation, str)
                or not source_limitation
                or len(source_limitation) > 128
            )
        )
        or (source_complete and source_limitation is not None)
    ):
        return None
    summary = rows[0].get("values") if isinstance(rows[0], Mapping) else None
    if not isinstance(summary, Mapping) or summary.get("record_kind") != "summary":
        return None
    excerpts = [
        values
        for row in rows[1:]
        if isinstance(row, Mapping)
        and isinstance((values := row.get("values")), Mapping)
        and values.get("record_kind") == "excerpt"
    ]
    if len(excerpts) != len(rows) - 1:
        return None
    heading = (
        f"## 관리되는 문서 근거 {len(excerpts)}건"
        if korean
        else f"## {len(excerpts)} governed document excerpts"
    )
    lines = [heading, ""]
    if not source_complete:
        lines.extend(
            [
                (
                    "문서 근거 범위가 불완전합니다. 이 발췌문을 전체 결과로 해석하면 안 됩니다. "
                    f"제한: `{_inline_code(str(source_limitation))}`"
                    if korean
                    else (
                        "Document coverage is incomplete. Do not treat these excerpts as "
                        "exhaustive. "
                        f"Limitation: `{_inline_code(str(source_limitation))}`"
                    )
                ),
                "",
            ]
        )
    if projection_truncated:
        lines.extend(
            [
                (
                    "표시 한도로 일부 문서 행이 생략됐습니다. 기술 상세에서 범위가 제한된 행을 "
                    "확인할 수 있습니다."
                    if korean
                    else (
                        "Some document rows were omitted by the display limit. "
                        "Bounded rows remain available in technical details."
                    )
                ),
                "",
            ]
        )
    if not excerpts:
        lines.append(
            (
                "접근 가능한 범위에서 관련 발췌문을 찾지 못했습니다. "
                "이는 문서가 없다는 증거가 아닙니다."
            )
            if korean
            else (
                "No admissible excerpt was found in the authorized scope. "
                "This does not prove that no relevant document exists."
            )
        )
    for excerpt in excerpts:
        source_name = excerpt.get("source_name")
        locator = excerpt.get("locator")
        revision = excerpt.get("document_revision")
        evidence_ref = excerpt.get("evidence_ref")
        text = excerpt.get("text")
        display_content_digest = excerpt.get("display_content_digest")
        redaction_applied = excerpt.get("redaction_applied")
        if (
            not isinstance(source_name, str)
            or not source_name
            or not isinstance(locator, str)
            or not locator
            or not isinstance(revision, str)
            or not revision
            or not isinstance(evidence_ref, str)
            or not evidence_ref
            or not isinstance(text, str)
            or not text
            or not isinstance(display_content_digest, str)
            or not display_content_digest.startswith("sha256:")
            or not isinstance(redaction_applied, bool)
        ):
            return None
        rendered_text, display_truncated = _bounded_document_text(text, maximum=1_200)
        lines.extend(
            [
                f"### {_escape_document_text(source_name, maximum=512)}",
                "",
                (
                    f"- 위치: `{_inline_code(locator)}`"
                    if korean
                    else f"- Location: `{_inline_code(locator)}`"
                ),
                (
                    f"- 문서 개정: `{_inline_code(revision)}`"
                    if korean
                    else f"- Document revision: `{_inline_code(revision)}`"
                ),
                (
                    f"- 근거 참조: `{_inline_code(evidence_ref)}`"
                    if korean
                    else f"- Evidence reference: `{_inline_code(evidence_ref)}`"
                ),
                (
                    f"- 표시 콘텐츠 다이제스트: `{_inline_code(display_content_digest)}`"
                    if korean
                    else (f"- Display content digest: `{_inline_code(display_content_digest)}`")
                ),
                *(
                    [
                        (
                            "- 표시 내용은 민감 값 규칙에 따라 제거되었습니다."
                            if korean
                            else "- Display text was redacted by the sensitive-value policy."
                        )
                    ]
                    if redaction_applied
                    else []
                ),
                *(
                    [
                        (
                            "- 표시 길이 제한으로 발췌문 일부만 보입니다. "
                            "전체 허용 본문은 기술 상세에 남아 있습니다."
                            if korean
                            else (
                                "- The excerpt is display-truncated. The complete admissible "
                                "text remains in technical details."
                            )
                        )
                    ]
                    if display_truncated
                    else []
                ),
                "",
                f"> {rendered_text}",
                "",
            ]
        )
    lines.append(
        "`instruction_authority=false`, `execution_authority=false`입니다."
        if korean
        else "The excerpts carry `instruction_authority=false` and `execution_authority=false`."
    )
    if output_shape != "governed_document_excerpts":
        lines.insert(
            2,
            (
                "이 문서 근거는 운영 관측을 보완하며 현재 상태의 권위를 대체하지 않습니다."
                if korean
                else (
                    "This document evidence supplements operational observations and does not "
                    "replace current-state authority."
                )
            ),
        )
        lines.insert(3, "")
    return "\n".join(lines)


def _is_governed_document_output(output: Mapping[str, object]) -> bool:
    rows = output.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    first = rows[0]
    return (
        isinstance(first, Mapping)
        and isinstance((values := first.get("values")), Mapping)
        and values.get("record_kind") == "summary"
        and "access_scope_digest" in values
        and "index_generation" in values
        and "retrieval_mode" in values
    )


def _escape_document_text(value: str, *, maximum: int) -> str:
    bounded = " ".join(value.split())[:maximum]
    escaped = bounded.replace("\\", "\\\\")
    for character in "`*_{}[]<>()#+-.!|":
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _bounded_document_text(value: str, *, maximum: int) -> tuple[str, bool]:
    normalized = " ".join(value.split())
    truncated = len(normalized) > maximum
    return _escape_document_text(normalized, maximum=maximum), truncated


def _inline_code(value: str) -> str:
    return value.replace("`", "'").replace("\r", " ").replace("\n", " ")[:512]


def _render_state_transition_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    if output_shape != "resource_state_transitions" or len(outputs) != 1:
        return None
    output = outputs[0]
    projected_rows = _condition_rows(output)
    if projected_rows is None:
        return None
    rows: list[Mapping[str, object]] = []
    unresolved = 0
    for row in projected_rows:
        conflicts = row.get("conflicts")
        trustworthy = (
            row.get("lane") == "observed"
            and row.get("authority") in {"provider", "telemetry"}
            and row.get("complete") is True
            and row.get("synthetic") is False
            and isinstance(conflicts, list)
            and not conflicts
        )
        if trustworthy:
            rows.append(row)
        else:
            unresolved += 1
    complete = output.get("source_complete") is True
    limitation = output.get("source_truncation_reason")
    if korean:
        heading = (
            "## 관측된 리소스 상태 전이"
            if rows
            else "## 상태 전이 근거 미확정"
            if unresolved
            else "## 검증된 상태 전이 없음"
            if complete
            else "## 상태 전이 확인 불가"
        )
        lines = [heading, ""]
        for row in rows[:20]:
            lines.append(
                "- "
                f"{row.get('effective_at') or '시각 미확인'} - "
                f"`{row.get('from_state') or 'unknown'}` -> "
                f"`{row.get('to_state') or 'unknown'}` "
                f"({row.get('state_type') or '상태 유형 미확인'})"
            )
        lines.append(f"- 원본 완전성: `{'complete' if complete else 'incomplete'}`")
        if unresolved:
            lines.append(f"- 미확정 상태 전이 근거: {unresolved}건")
        if output.get("display_truncated") is True:
            total_rows = output.get("total_rows")
            lines.append(
                f"- 표시한 상태 전이: {len(rows)}개 / "
                f"{total_rows if isinstance(total_rows, int) else '20개 초과'}"
            )
        if isinstance(limitation, str) and limitation:
            lines.append(f"- 제한 사항: `{limitation}`")
        lines.extend(["", "`execution_authority=false`"])
        return "\n".join(lines)
    heading = (
        "## Observed resource state transitions"
        if rows
        else "## Resource state transition evidence unresolved"
        if unresolved
        else "## No verified state transitions"
        if complete
        else "## Resource state transitions unavailable"
    )
    lines = [heading, ""]
    for row in rows[:20]:
        lines.append(
            "- "
            f"{row.get('effective_at') or 'time unavailable'} - "
            f"`{row.get('from_state') or 'unknown'}` -> "
            f"`{row.get('to_state') or 'unknown'}` "
            f"({row.get('state_type') or 'state type unavailable'})"
        )
    lines.append(f"- Source completeness: `{'complete' if complete else 'incomplete'}`")
    if unresolved:
        lines.append(f"- Unresolved transition evidence: {unresolved}")
    if output.get("display_truncated") is True:
        total_rows = output.get("total_rows")
        lines.append(
            f"- Displayed transitions: {len(rows)} of "
            f"{total_rows if isinstance(total_rows, int) else 'more than 20'}"
        )
    if isinstance(limitation, str) and limitation:
        lines.append(f"- Limitation: `{limitation}`")
    lines.extend(["", "This result is read-only and has `execution_authority=false`."])
    return "\n".join(lines)


def _render_resource_condition_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    measure_concepts: tuple[str, ...],
) -> str | None:
    """Render each requested condition under its own evidence family."""

    if output_shape != "resource_condition_sections" or len(outputs) != 2:
        return None
    by_node = {
        output.get("node_id"): output
        for output in outputs
        if isinstance(output.get("node_id"), str)
    }
    state_output = by_node.get("resource-condition-power")
    health_output = by_node.get("resource-condition-health")
    if not isinstance(state_output, Mapping) or not isinstance(health_output, Mapping):
        return None
    state_concepts = tuple(item for item in measure_concepts if item.startswith("resource_state."))
    health_concepts = tuple(
        item for item in measure_concepts if item.startswith("resource_health.")
    )
    if not state_concepts or not health_concepts:
        return None
    state_rows = _condition_rows(state_output)
    health_rows = _condition_rows(health_output)
    if state_rows is None or health_rows is None:
        return None
    sections = (
        (
            "inventory power state",
            "inventory 전원 상태",
            state_concepts,
            state_rows,
            state_output,
            "state_concept",
        ),
        (
            "Resource Health",
            "Resource Health",
            health_concepts,
            health_rows,
            health_output,
            "health_concept",
        ),
    )
    if korean:
        lines = [
            "## 리소스 상태 확인 결과",
            "",
            "요청한 상태를 서로 다른 두 authoritative source에서 독립적으로 확인했습니다.",
            "",
        ]
    else:
        lines = [
            "## Resource condition results",
            "",
            "The requested conditions were checked independently against two "
            "authoritative sources.",
            "",
        ]
    for english_source, korean_source, concepts, rows, output, concept_field in sections:
        complete = output.get("source_complete") is True
        display_complete = complete and output.get("display_truncated") is not True
        limitation = output.get("source_truncation_reason")
        source = korean_source if korean else english_source
        lines.extend([f"### {source}", ""])
        for concept in concepts:
            matches = tuple(
                row
                for row in rows
                if row.get(concept_field) == concept
                or (
                    concept_field == "health_concept"
                    and isinstance(
                        (matching_concepts := row.get("matching_health_concepts")),
                        list,
                    )
                    and concept in matching_concepts
                )
            )
            status = (
                "matched" if matches else "verified_empty" if display_complete else "unresolved"
            )
            names = tuple(
                str(name) for row in matches if isinstance((name := row.get("name")), str) and name
            )
            label = concept.rsplit(".", 1)[-1].replace("_", " ")
            lines.append(
                f"- `{label}`: `{status}`"
                + (f" - {', '.join(f'`{name}`' for name in names[:8])}" if names else "")
            )
        lines.append(
            f"- source completeness: `{'complete' if complete else 'incomplete'}`"
            if not korean
            else f"- 원본 완전성: `{'complete' if complete else 'incomplete'}`"
        )
        if isinstance(limitation, str) and limitation:
            lines.append(f"- {'제한 사항' if korean else 'limitation'}: `{limitation}`")
        if output.get("display_truncated") is True:
            lines.append(
                "- 표시 범위가 잘려 있어 보이지 않는 일치 항목을 배제할 수 없습니다."
                if korean
                else "- Display rows are truncated; unseen matches cannot be excluded."
            )
        lines.append("")
    lines.append(
        "`execution_authority=false`"
        if korean
        else "This result is read-only and has `execution_authority=false`."
    )
    return "\n".join(lines)


def _condition_rows(output: Mapping[str, object]) -> tuple[Mapping[str, object], ...] | None:
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None
    projected: list[Mapping[str, object]] = []
    for row in rows:
        values = row.get("values") if isinstance(row, Mapping) else None
        if not isinstance(values, Mapping) or values.get("execution_authority") is not False:
            return None
        projected.append(values)
    return tuple(projected)


def _render_ontology_declaration_count_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
    subject_constraints: tuple[str, ...],
) -> str | None:
    """Render only complete declaration counts from the verified aggregate output."""

    if output_shape != "aggregation_table" or len(outputs) != 1 or len(subject_constraints) != 1:
        return None
    try:
        declaration_kind = OntologyDeclarationKind(subject_constraints[0])
    except ValueError:
        return None
    output = outputs[0]
    complete = output.get("source_complete") is True and output.get("display_truncated") is not True
    rows = output.get("rows")
    row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    values = row.get("values") if isinstance(row, Mapping) else None
    group = values.get("group") if isinstance(values, Mapping) else None
    group_kind = group.get("kind") if isinstance(group, Mapping) else None
    value = values.get("value") if isinstance(values, Mapping) else None
    valid_count = (
        isinstance(values, Mapping)
        and values.get("operation") == "count"
        and group_kind in {None, declaration_kind.value}
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )
    if not complete or not valid_count:
        if korean:
            return (
                "## 온톨로지 선언 개수를 확인할 수 없음\n\n"
                "- 활성 온톨로지 release의 선언 매니페스트가 완전하지 않아 정확한 개수를 "
                "보고하지 않습니다.\n"
                "- 읽기 전용 출처: `query.manifest`.\n\n"
                "이 결과는 실행 권한을 부여하지 않습니다."
            )
        return (
            "## Ontology declaration count unavailable\n\n"
            "- The active ontology release manifest is incomplete, so an exact count is not "
            "reported.\n"
            "- Read-only source: `query.manifest`.\n\n"
            "This result grants no execution authority."
        )
    label = f"{declaration_kind.value[:1].upper()}{declaration_kind.value[1:]}Types"
    heading = "## 검증된 온톨로지 선언 개수" if korean else "## Verified ontology declaration count"
    lines = [heading, ""]
    lines.append(f"- {label}: {value}")
    lines.extend(
        [
            (
                "- 읽기 전용 출처: 활성 온톨로지 release에 대해 역할과 목적으로 범위가 제한된 "
                "`query.manifest`."
                if korean
                else (
                    "- Read-only source: role- and purpose-scoped `query.manifest` for the active "
                    "ontology release."
                )
            ),
            "",
            (
                "각 값은 매니페스트의 서로 다른 선언 개수입니다. 이 결과는 실행 권한을 부여하지 "
                "않습니다."
                if korean
                else (
                    "Each value is the distinct declaration count from the manifest. "
                    "This result grants no execution authority."
                )
            ),
        ]
    )
    return "\n".join(lines)


def _render_generic_empty_query_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render zero-row tables without presenting an empty result as positive verification."""

    counted = [
        output
        for output in outputs
        if isinstance(output.get("returned_rows"), int)
        and not isinstance(output.get("returned_rows"), bool)
        and isinstance(output.get("total_rows"), int)
        and not isinstance(output.get("total_rows"), bool)
    ]
    if (
        not counted
        or len(counted) != len(outputs)
        or any(output["returned_rows"] != 0 or output["total_rows"] != 0 for output in counted)
    ):
        return None
    complete = all(output.get("source_complete") is True for output in counted)
    limitations = tuple(
        dict.fromkeys(
            reason
            for output in counted
            if isinstance((reason := output.get("source_truncation_reason")), str)
            and reason.strip()
        )
    )
    if korean:
        if output_shape == "resource_state_list":
            lines = [
                (
                    "## 실행 중이 아닌 리소스 없음"
                    if complete
                    else "## 확인 범위에서 실행 중이 아닌 리소스 없음"
                ),
                "",
                (
                    "- 검증된 전체 조회 범위에서 실행 중이 아닌 리소스가 없습니다."
                    if complete
                    else (
                        "- 현재 확인 가능한 범위에서는 실행 중이 아닌 리소스를 찾지 못했습니다. "
                        "인벤토리 범위가 완전하지 않아 전체에 없다고 단정할 수 없습니다."
                    )
                ),
            ]
        else:
            lines = [
                "## 일치하는 관측 근거 없음" if complete else "## 근거가 충분하지 않음",
                "",
                (
                    "- 검증된 조회 범위에서 일치하는 행이 반환되지 않았습니다."
                    if complete
                    else "- 반환된 행은 없지만 원본 근거가 완전하지 않아 부재를 판단할 수 없습니다."
                ),
            ]
        if limitations:
            lines.append(f"- 근거 한계: `{', '.join(limitations)}`")
        lines.extend(
            [
                "- 행 0개는 검증된 조회 범위를 벗어난 실제 리소스의 부재를 증명하지 않습니다.",
                "",
                "`execution_authority=false`",
            ]
        )
        return "\n".join(lines)
    if output_shape == "resource_state_list":
        lines = [
            "## No non-running resources" if complete else "## No non-running resources in scope",
            "",
            (
                "- The complete verified scope contains no non-running resources."
                if complete
                else (
                    "- No non-running resources were found in the currently verified scope. "
                    "The inventory scope is incomplete, so this does not establish global absence."
                )
            ),
        ]
    else:
        lines = [
            "## No matching observed evidence" if complete else "## Evidence is insufficient",
            "",
            (
                "- The verified query scope returned no matching rows."
                if complete
                else (
                    "- No rows were returned, but incomplete source evidence cannot establish "
                    "absence."
                )
            ),
        ]
    if limitations:
        lines.append(f"- Evidence limitation: `{', '.join(limitations)}`")
    lines.extend(
        [
            "- Zero rows do not prove that no real resources exist outside the "
            "verified query scope.",
            "",
            "`execution_authority=false`",
        ]
    )
    return "\n".join(lines)


def _render_resource_event_history_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render bounded Resource Events without turning incomplete zero rows into absence."""

    if output_shape != "resource_event_history" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None
    projected_events: list[Mapping[str, object]] = []
    for row in rows:
        values = row.get("values") if isinstance(row, Mapping) else None
        if not isinstance(values, Mapping):
            return None
        projected_events.append(values)
    returned_rows = output.get("returned_rows")
    total_rows = output.get("total_rows")
    if (
        not isinstance(returned_rows, int)
        or isinstance(returned_rows, bool)
        or returned_rows != len(projected_events)
        or not isinstance(total_rows, int)
        or isinstance(total_rows, bool)
        or total_rows < returned_rows
    ):
        return None
    events = projected_events[-8:]
    display_truncated = len(events) < total_rows
    complete = output.get("source_complete") is True
    limitation = output.get("source_truncation_reason")
    limitation_text = limitation if isinstance(limitation, str) else None
    if korean:
        lines = ["## 관측된 Resource Event", ""]
        if events:
            for event in events:
                lines.append(
                    "- "
                    f"{event.get('occurred_at', '시각 미확인')} - "
                    f"`{event.get('name') or '이름 미확인'}` "
                    f"({event.get('type') or '유형 미확인'}): "
                    f"{event.get('event_kind') or 'event 종류 미확인'} / "
                    f"{event.get('status') or '상태 미확인'} / "
                    f"{event.get('classification') or '분류 미확인'}"
                )
        else:
            lines.append("- 요청한 구간에서 반환된 Resource Event가 없습니다.")
        lines.extend(["", "## 근거 한계", ""])
        lines.append(f"- 원본 완전성: {'complete' if complete else 'incomplete'}")
        if total_rows:
            lines.append(f"- 표시한 Resource Event: 전체 {total_rows}개 중 {len(events)}개")
        if display_truncated:
            lines.append(
                f"- 표시 제한: `display_truncated`; 가장 최근 {len(events)}개를 "
                "시간순으로 표시합니다."
            )
        if not complete:
            lines.append(f"- 제한 사항: `{limitation_text or 'source_incomplete'}`")
        if limitation_text == "source_retention_unverified":
            lines.append(
                "- Kubernetes Event 보존 기간이 권위 있게 확인되지 않았으므로 "
                "행 0개는 과거 Event 부재를 증명하지 않습니다."
            )
        lines.extend(["", "`execution_authority=false`"])
        return "\n".join(lines)
    lines = ["## Observed Resource Events", ""]
    if events:
        for event in events:
            lines.append(
                "- "
                f"{event.get('occurred_at', 'time unavailable')} - "
                f"`{event.get('name') or 'name unavailable'}` "
                f"({event.get('type') or 'type unavailable'}): "
                f"{event.get('event_kind') or 'event kind unavailable'} / "
                f"{event.get('status') or 'status unavailable'} / "
                f"{event.get('classification') or 'classification unavailable'}"
            )
    else:
        lines.append("- No Resource Events were returned for the requested window.")
    lines.extend(["", "## Evidence limitations", ""])
    lines.append(f"- Source completeness: {'complete' if complete else 'incomplete'}")
    if total_rows:
        lines.append(f"- Displayed Resource Events: {len(events)} of {total_rows}.")
    if display_truncated:
        lines.append(
            f"- Display limitation: `display_truncated`; showing the most recent {len(events)} "
            "in chronological order."
        )
    if not complete:
        lines.append(f"- Limitation: `{limitation_text or 'source_incomplete'}`")
    if limitation_text == "source_retention_unverified":
        lines.append(
            "- Kubernetes Event retention is not authoritative, so zero rows do not prove "
            "historical absence."
        )
    lines.extend(["", "`execution_authority=false`"])
    return "\n".join(lines)


def _render_target_candidates_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Name bounded verified candidates instead of returning a context-only hold."""

    if output_shape != "resource_target_candidates" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if not isinstance(rows, list):
        return None
    candidates: list[tuple[str, str | None]] = []
    for row in rows[:8]:
        values = row.get("values") if isinstance(row, Mapping) else None
        if not isinstance(values, Mapping):
            continue
        name = values.get("name")
        resource_type = values.get("type")
        if not isinstance(name, str) or not name.strip():
            continue
        candidates.append(
            (
                name.strip(),
                resource_type.strip()
                if isinstance(resource_type, str) and resource_type.strip()
                else None,
            )
        )
    total = output.get("total_rows")
    total_count = total if isinstance(total, int) and total >= 0 else len(candidates)
    complete = output.get("source_complete") is True
    limitation = output.get("source_truncation_reason")
    if korean:
        lines = ["## 확인된 대상 후보", ""]
        if candidates:
            lines.extend(
                f"- `{name}`" + (f" ({resource_type})" if resource_type is not None else "")
                for name, resource_type in candidates
            )
        else:
            lines.append("- 현재 검증된 inventory에서 일치하는 대상 후보를 찾지 못했습니다.")
        lines.extend(
            [
                "",
                "## 범위와 다음 단계",
                "",
                f"- 검증된 후보 수: {total_count}",
                f"- 후보 범위 완전성: {'complete' if complete else 'incomplete'}",
            ]
        )
        if not complete:
            lines.append(f"- 제한 사항: {str(limitation or 'inventory_scope_incomplete')}")
        if candidates:
            lines.append(
                "- 위 후보 중 확인할 리소스의 정확한 이름 또는 리소스 ID를 지정하면 "
                "요청한 운영 근거를 이어서 검증할 수 있습니다."
            )
        lines.extend(["", "`execution_authority=false`"])
        return "\n".join(lines)
    lines = ["## Verified target candidates", ""]
    if candidates:
        lines.extend(
            f"- `{name}`" + (f" ({resource_type})" if resource_type is not None else "")
            for name, resource_type in candidates
        )
    else:
        lines.append("- No matching target candidate was found in the verified inventory.")
    lines.extend(
        [
            "",
            "## Scope and next step",
            "",
            f"- Verified candidate count: {total_count}",
            f"- Candidate scope completeness: {'complete' if complete else 'incomplete'}",
        ]
    )
    if not complete:
        lines.append(f"- Limitation: {str(limitation or 'inventory_scope_incomplete')}")
    if candidates:
        lines.append(
            "- Provide the exact resource name or resource ID from the candidates above to "
            "continue with the requested operational evidence read."
        )
    lines.extend(["", "`execution_authority=false`"])
    return "\n".join(lines)


def _render_error_activity_correlation_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render aligned error windows and Activity Log evidence without a cause claim."""

    if output_shape != "target_error_activity_correlation" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if (
        output.get("node_id") != "target-error-activity-correlation"
        or not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], Mapping)
    ):
        return None
    values = rows[0].get("values")
    if (
        not isinstance(values, Mapping)
        or values.get("causal_claim_supported") is not False
        or values.get("execution_authority") is not False
    ):
        return None
    fields = (
        ("error_trend", "요청 오류 추세", "Request error trend"),
        ("baseline_error_total", "직전 구간 오류", "Baseline errors"),
        ("current_error_total", "현재 구간 오류", "Current errors"),
        ("activity_state", "Activity Log", "Activity Log"),
        ("activity_change_count", "변경 이벤트 수", "Change events"),
        ("correlation_assessment", "상관 평가", "Correlation assessment"),
    )
    assessments = [
        f"- {korean_label if korean else english_label}: {_readable_health_token(values.get(key))}."
        for key, korean_label, english_label in fields
        if values.get(key) is not None
    ]
    windows = [
        f"- {label}: {value}."
        for label, value in (
            (
                "직전 구간 시작" if korean else "Baseline window start",
                values.get("baseline_window_start"),
            ),
            (
                "직전 구간 종료" if korean else "Baseline window end",
                values.get("baseline_window_end"),
            ),
            (
                "현재 구간 시작" if korean else "Current window start",
                values.get("current_window_start"),
            ),
            (
                "현재 구간 종료" if korean else "Current window end",
                values.get("current_window_end"),
            ),
        )
        if isinstance(value, str) and value
    ]
    raw_gaps = values.get("evidence_gaps")
    gaps = (
        [item.strip() for item in raw_gaps.split(",") if item.strip()]
        if isinstance(raw_gaps, str)
        else []
    )
    gap_lines = [f"- {_readable_health_token(item)}." for item in gaps]
    trend = _readable_health_token(values.get("error_trend"))
    correlation = _readable_health_token(values.get("correlation_assessment"))
    if korean:
        return (
            "## 요청 오류와 Activity Log 상관 평가\n\n"
            f"**요청 오류 추세는 {trend}이며 상관 평가는 {correlation}입니다.**\n\n"
            "## 관측 결과\n\n"
            + "\n".join(assessments)
            + "\n\n## 근거 구간\n\n"
            + ("\n".join(windows) if windows else "- 검증된 구간이 없습니다.")
            + "\n\n## 근거 공백\n\n"
            + ("\n".join(gap_lines) if gap_lines else "- 추가 공백이 기록되지 않았습니다.")
            + "\n\n같은 구간의 동시 관측은 인과관계를 입증하지 않습니다."
            + "\n\n## 권한\n\n- 읽기 전용이며 `execution_authority=false`입니다."
        )
    return (
        "## Request errors and Activity Log correlation\n\n"
        f"**Request error trend is {trend}; correlation is {correlation}.**\n\n"
        "## Observations\n\n"
        + "\n".join(assessments)
        + "\n\n## Evidence windows\n\n"
        + ("\n".join(windows) if windows else "- No verified window is available.")
        + "\n\n## Evidence gaps\n\n"
        + ("\n".join(gap_lines) if gap_lines else "- No additional gaps were recorded.")
        + "\n\nCo-occurrence in the same window does not establish causation."
        + "\n\n## Authority\n\n- Read-only; `execution_authority=false`."
    )


def _render_health_query_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render one typed target-health assessment without upgrading missing evidence."""

    if output_shape != "target_health_assessment" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if output.get("node_id") != "target-health-assessment" or not isinstance(rows, list):
        return None
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    values = rows[0].get("values")
    if not isinstance(values, Mapping):
        return None
    if values.get("evidence_sufficient") is not False:
        return None
    fields = (
        ("platform_lifecycle", "플랫폼 수명 주기", "Platform lifecycle"),
        ("readiness", "준비 상태", "Readiness"),
        ("application_service_health", "애플리케이션 서비스", "Application service"),
        ("stability", "안정성", "Stability"),
        ("resource_pressure", "리소스 압력", "Resource pressure"),
        ("request_telemetry", "요청 텔레메트리", "Request telemetry"),
    )
    assessments = [
        f"- {korean_label if korean else english_label}: {_readable_health_token(values.get(key))}."
        for key, korean_label, english_label in fields
        if values.get(key) is not None
    ]
    freshness = [
        f"- {label}: {value}."
        for label, value in (
            (
                "원본 관측 시각" if korean else "Source observation",
                values.get("source_observed_at"),
            ),
            ("인벤토리 조회 시각" if korean else "Inventory read", values.get("inventory_read_at")),
            (
                "메트릭 구간 종료" if korean else "Metric window end",
                values.get("metric_window_end"),
            ),
        )
        if isinstance(value, str) and value
    ]
    raw_gaps = values.get("evidence_gaps")
    gaps = (
        [item.strip() for item in raw_gaps.split(",") if item.strip()]
        if isinstance(raw_gaps, str)
        else []
    )
    gap_lines = [f"- {_readable_health_token(item)}." for item in gaps]
    if korean:
        return (
            "## 건강 근거 평가\n\n"
            "**아니요. 현재 근거만으로 전체 애플리케이션 서비스가 건강하다고 "
            "주장하기에는 불충분합니다.**\n\n"
            "## 영역별 평가\n\n"
            + "\n".join(assessments)
            + "\n\n## 근거 시각\n\n"
            + ("\n".join(freshness) if freshness else "- 검증된 원본 시각이 없습니다.")
            + "\n\n## 근거 공백\n\n"
            + ("\n".join(gap_lines) if gap_lines else "- 추가 공백이 기록되지 않았습니다.")
            + "\n\n## 권한\n\n- 읽기 전용이며 `execution_authority=false`입니다."
        )
    return (
        "## Health evidence assessment\n\n"
        "**No. Current evidence is insufficient to claim full application-service health.**\n\n"
        "## Assessment by area\n\n"
        + "\n".join(assessments)
        + "\n\n## Evidence freshness\n\n"
        + ("\n".join(freshness) if freshness else "- No verified source time is available.")
        + "\n\n## Evidence gaps\n\n"
        + ("\n".join(gap_lines) if gap_lines else "- No additional gaps were recorded.")
        + "\n\n## Authority\n\n- Read-only; `execution_authority=false`."
    )


def _readable_health_token(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str) and value:
        return value.replace("_", " ")
    return "not proven"


_CURRENT_STATE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("provisioning_status", "프로비저닝 상태", "Provisioning status"),
    ("running_status", "실행 상태", "Running status"),
    ("revision_name", "최신 리비전", "Latest revision"),
    ("ready_revision_name", "준비된 리비전", "Ready revision"),
)


def _render_current_state_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """State one exact target's read current-state fields and every unobserved field."""

    if output_shape != "target_current_state" or len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if output.get("node_id") != "resource-current-state" or not isinstance(rows, list):
        return None
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        return None
    values = rows[0].get("values")
    if not isinstance(values, Mapping):
        return None
    name = _readable_state_text(values.get("name"))
    if name is None:
        return None
    # Every reported field is listed even when unobserved. Listing only populated fields
    # would let an unreported status read as a healthy one. A field the capability did not
    # report does not apply to this resource type, so naming it would invent a gap.
    unobserved = "관측되지 않음" if korean else "not observed"
    state_lines = [
        f"- {korean_label if korean else english_label}: "
        f"{_readable_state_text(values.get(key)) or unobserved}."
        for key, korean_label, english_label in _CURRENT_STATE_FIELDS
        if key in values
    ]
    freshness = [
        f"- {label}: {value or unobserved}."
        for label, value in (
            (
                "원본 관측 시각" if korean else "Source observation",
                _readable_state_text(values.get("source_observed_at")),
            ),
            (
                "인벤토리 조회 시각" if korean else "Inventory read",
                _readable_state_text(values.get("inventory_read_at")),
            ),
        )
    ]
    gap_lines = [
        f"- {_readable_health_token(item)}."
        for item in _split_truncation_reason(output.get("source_truncation_reason"))
    ]
    assessment = _readable_state_text(values.get("target_state_assessment"))
    related_resources_assessed = values.get("related_resources_assessed") is True
    assessment_lines = _current_state_assessment_lines(
        assessment,
        related_resources_assessed=related_resources_assessed,
        korean=korean,
    )
    if korean:
        return (
            f"## `{name}`의 검증된 현재 상태\n\n"
            + "\n".join(state_lines)
            + "\n\n## 비정상 리소스 판정\n\n"
            + "\n".join(assessment_lines)
            + "\n\n## 근거 시각\n\n"
            + "\n".join(freshness)
            + "\n\n## 근거 공백\n\n"
            + (
                "\n".join(gap_lines)
                if gap_lines
                else "- 요청한 현재 상태 필드에는 기록된 공백이 없습니다."
            )
            + "\n- 이 결과는 지정한 대상 1개의 현재 상태만 포함하며, 그 범위 밖의 리소스가 "
            "정상인지 여부는 판정하지 않았습니다.\n"
            "- 프로바이더가 보고한 상태는 관측이며 원인이 아닙니다.\n\n"
            "## 권한\n\n- 읽기 전용이며 `execution_authority=false`입니다."
        )
    return (
        f"## Verified current state for `{name}`\n\n"
        + "\n".join(state_lines)
        + "\n\n## Abnormal resource assessment\n\n"
        + "\n".join(assessment_lines)
        + "\n\n## Evidence freshness\n\n"
        + "\n".join(freshness)
        + "\n\n## Evidence gaps\n\n"
        + (
            "\n".join(gap_lines)
            if gap_lines
            else "- No gap was recorded for the requested current-state fields."
        )
        + "\n- This result covers only the one named target; it does not judge whether any "
        "resource outside that scope is healthy.\n"
        "- Provider-reported status is an observation, not a cause.\n\n"
        "## Authority\n\n- Read-only; `execution_authority=false`."
    )


def _readable_state_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _current_state_assessment_lines(
    assessment: str | None,
    *,
    related_resources_assessed: bool,
    korean: bool,
) -> tuple[str, str]:
    assessment_key = assessment or ""
    target = {
        "observed_running": (
            "- 지정한 대상: 프로바이더 lifecycle 상태에서 비정상 징후가 관측되지 않았습니다."
            if korean
            else "- Named target: no abnormal provider lifecycle state was observed."
        ),
        "observed_not_running": (
            "- 지정한 대상: 프로바이더 lifecycle 상태에서 비정상 징후가 관측되었습니다."
            if korean
            else "- Named target: an abnormal provider lifecycle state was observed."
        ),
    }.get(
        assessment_key,
        (
            "- 지정한 대상: 비정상 여부를 판정할 상태 근거가 충분하지 않습니다."
            if korean
            else "- Named target: state evidence is insufficient to assess abnormality."
        ),
    )
    related = (
        (
            "- 연관 리소스: 이 조회에서 상태가 평가되었습니다."
            if korean
            else "- Related resources: their state was assessed by this read."
        )
        if related_resources_assessed
        else (
            "- 연관 노드·워크로드·리소스: 이번 exact-target 조회에 포함되지 않았습니다. "
            "따라서 비정상 리소스가 없다고 판정하지 않습니다."
            if korean
            else "- Related nodes, workloads, and resources: not included in this exact-target "
            "read, so the absence of abnormal resources is not proven."
        )
    )
    return target, related


def _split_truncation_reason(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(item for item in (part.strip() for part in value.split("+")) if item)


def _render_impact_query_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Explain one typed exact-target service-impact result without inferring edges."""

    if output_shape != "inventory_impact" or len(outputs) != 1:
        return None
    output = outputs[0]
    if output.get("node_id") != "impact-services":
        return None
    returned = output.get("returned_rows")
    total = output.get("total_rows")
    complete = output.get("source_complete") is True
    if not isinstance(returned, int) or isinstance(returned, bool):
        return None
    if not isinstance(total, int) or isinstance(total, bool):
        return None
    if korean:
        completeness = (
            "현재 검토된 관계 범위에서 조회가 완전하게 끝났습니다."
            if complete
            else "관계 탐색 근거가 불완전하므로 추가 영향이 남아 있을 수 있습니다."
        )
        return (
            "## 검증된 영향 범위\n\n"
            f"- 관측된 영향 서비스: {total}개.\n"
            f"- 화면에 담긴 서비스: {returned}개.\n"
            "- 조회한 검토 경로: `BusinessService -> implemented_by -> Workload -> "
            "workload_runs_on -> Resource`.\n"
            "- 추론만으로 영향 대상으로 승격한 서비스: 0개.\n\n"
            "## 근거 공백\n\n"
            f"- {completeness}\n"
            "- 현재 온톨로지에 투영되지 않은 외부 또는 애플리케이션 수준 의존성은 이 결과의 "
            "범위 밖입니다. 0개 행은 실제 영향이 없다는 뜻이 아닙니다.\n\n"
            "## 권한\n\n"
            "- 읽기 전용이며 `execution_authority=false`입니다."
        )
    completeness = (
        "The query completed over the current reviewed relationship scope."
        if complete
        else "Relationship evidence is incomplete, so additional impact can remain unobserved."
    )
    return (
        "## Verified impact scope\n\n"
        f"- Observed impacted services: {total}.\n"
        f"- Services carried for display: {returned}.\n"
        "- Reviewed path queried: `BusinessService -> implemented_by -> Workload -> "
        "workload_runs_on -> Resource`.\n"
        "- Services promoted from inference alone: 0.\n\n"
        "## Evidence gaps\n\n"
        f"- {completeness}\n"
        "- External or application-level dependencies not projected into the current ontology are "
        "outside this result. Zero rows do not prove zero real-world impact.\n\n"
        "## Authority\n\n"
        "- Read-only; `execution_authority=false`."
    )


def _render_causal_query_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    additional_limitations: Sequence[str] = (),
) -> str | None:
    comparison: Mapping[str, object] | None = None
    hypotheses: list[Mapping[str, object]] = []
    activity_output: Mapping[str, object] | None = None
    for output in outputs:
        if output.get("node_id") == "change-activity":
            activity_output = output
        summary = output.get("summary")
        if not isinstance(summary, Mapping):
            continue
        if output.get("result_kind") == "metric.comparison":
            comparison = summary
        elif output.get("result_kind") == "causal.join":
            hypotheses.append(summary)
    if comparison is None or not hypotheses:
        return None

    supported = [item for item in hypotheses if item.get("status") == "supported"]
    refuted = [item for item in hypotheses if item.get("status") == "refuted"]
    unresolved = [item for item in hypotheses if item.get("status") == "unresolved"]
    strongest = max(supported, key=_causal_hypothesis_strength, default=None)
    target = _answer_text(comparison.get("resource_id"))
    symptom = _answer_text(comparison.get("concept_id"))
    comparison_complete = comparison.get("complete") is True
    unit = _answer_text(comparison.get("unit"), fallback="")
    baseline_value = _answer_measure(comparison.get("baseline_value"), unit)
    current_value = _answer_measure(comparison.get("current_value"), unit)
    absolute_change = _answer_measure(comparison.get("absolute_change"), unit)
    baseline_window = _answer_window(
        comparison.get("baseline_start"),
        comparison.get("baseline_end"),
    )
    current_window = _answer_window(
        comparison.get("current_start"),
        comparison.get("current_end"),
    )
    limitations = _causal_limitations(comparison, hypotheses)
    limitations.extend(additional_limitations)
    if activity_output is not None and activity_output.get("source_complete") is not True:
        activity_limitation = activity_output.get("source_truncation_reason")
        limitations.append(_answer_text(activity_limitation, fallback="change_activity_incomplete"))
    limitations = list(dict.fromkeys(limitations))
    activity_lines, activity_evidence_refs = _change_activity_lines(
        activity_output,
        korean=korean,
    )
    evidence_refs = _causal_evidence_refs(outputs, activity_evidence_refs)
    if len(hypotheses) < 2:
        limitations.insert(
            0,
            "검증된 경쟁 가설이 두 개 미만입니다."
            if korean
            else "Fewer than two competing hypotheses were verified.",
        )

    if korean:
        strongest_line = (
            f"- 가장 강한 원인 후보: `{_answer_text(strongest.get('hypothesis_id'))}`"
            if strongest is not None
            else "- 가장 강한 원인 후보: 현재 근거로 확정할 수 없습니다."
        )
        lines = [
            "## 확인된 관측 사실",
            "",
            f"- 정확한 대상: `{target}`",
            (
                f"- 검증된 증상: `{symptom}` 증가"
                if comparison_complete
                else f"- 요청된 증상 방향: `{symptom}` 증가; 측정 근거: unavailable"
            ),
            f"- 기준 구간: {baseline_window}, 측정값 {baseline_value}",
            f"- 현재 구간: {current_window}, 측정값 {current_value}",
            f"- 실제 측정 변화: {absolute_change}",
            "",
            "## 변경 및 배포 근거",
            "",
            *activity_lines,
            "",
            "## 원인 판단",
            "",
            strongest_line,
            _causal_confidence_basis(
                strongest,
                supported=len(supported),
                refuted=len(refuted),
                unresolved=len(unresolved),
                korean=True,
            ),
            "- 이 순위는 판정 상태, 근거 등급, 표본 수, 상관 강도를 사용하며 "
            "시간적 인접성만으로 인과를 확정하지 않습니다.",
            "",
            "## 경쟁 가설",
            "",
            *_causal_hypothesis_lines(hypotheses, korean=True),
            "",
            "## 배제되거나 남아 있는 후보",
            "",
            f"- 반증됨: {_hypothesis_names(refuted, korean=True)}",
            f"- 미해결: {_hypothesis_names(unresolved, korean=True)}",
            "",
            "## 제한 사항",
            "",
            *([f"- {item}" for item in limitations] or ["- 기록된 추가 제한 사항이 없습니다."]),
            "",
            "## 근거 참조",
            "",
            *([f"- `{item}`" for item in evidence_refs] or ["- 검증된 근거 참조가 없습니다."]),
            "",
            "## 다음 안전 단계",
            "",
            (
                "정확한 대상의 request 및 dependency duration telemetry 수집 상태를 확인한 뒤 "
                "같은 기준/현재 구간을 읽기 전용으로 다시 조회하세요. "
                "이 답변은 변경을 실행하거나 승인하지 않습니다."
                if not comparison_complete
                else "누락되거나 오래되거나 충돌하는 근거 source를 같은 대상과 시간 범위에서 "
                "읽기 전용으로 다시 확인하세요. 이 답변은 변경을 실행하거나 승인하지 않습니다."
            ),
            "",
            "`execution_authority=false`",
        ]
        return "\n".join(lines)

    strongest_line = (
        f"- Strongest cause candidate: `{_answer_text(strongest.get('hypothesis_id'))}`"
        if strongest is not None
        else "- Strongest cause candidate: current evidence does not establish one."
    )
    lines = [
        "## Verified observations",
        "",
        f"- Exact target: `{target}`",
        (
            f"- Verified symptom: `{symptom}` increased"
            if comparison_complete
            else f"- Requested symptom direction: `{symptom}` increase; measurement: unavailable"
        ),
        f"- Baseline window: {baseline_window}, measured {baseline_value}",
        f"- Current window: {current_window}, measured {current_value}",
        f"- Measured change: {absolute_change}",
        "",
        "## Change and deployment evidence",
        "",
        *activity_lines,
        "",
        "## Cause assessment",
        "",
        strongest_line,
        _causal_confidence_basis(
            strongest,
            supported=len(supported),
            refuted=len(refuted),
            unresolved=len(unresolved),
            korean=False,
        ),
        "- Ranking uses disposition, evidence grade, sample count, and correlation strength. "
        "Temporal proximity alone is not treated as causal proof.",
        "",
        "## Competing hypotheses",
        "",
        *_causal_hypothesis_lines(hypotheses, korean=False),
        "",
        "## Excluded and remaining candidates",
        "",
        f"- Refuted: {_hypothesis_names(refuted, korean=False)}",
        f"- Unresolved: {_hypothesis_names(unresolved, korean=False)}",
        "",
        "## Limitations",
        "",
        *([f"- {item}" for item in limitations] or ["- No additional limitations were recorded."]),
        "",
        "## Evidence references",
        "",
        *(
            [f"- `{item}`" for item in evidence_refs]
            or ["- No verified evidence references were available."]
        ),
        "",
        "## Next safe step",
        "",
        (
            "Verify request and dependency duration telemetry collection for the exact target, "
            "then repeat the same baseline and current windows as read-only queries. "
            "This answer does not execute or approve a change."
            if not comparison_complete
            else "Recheck the missing, stale, or conflicting evidence sources under the same "
            "target and time bounds using read-only queries. This answer does not execute or "
            "approve a change."
        ),
        "",
        "`execution_authority=false`",
    ]
    return "\n".join(lines)


def _causal_evidence_refs(
    outputs: list[dict[str, object]],
    activity_refs: list[str],
) -> list[str]:
    refs = list(activity_refs)
    for output in outputs:
        raw = output.get("evidence_refs")
        if isinstance(raw, list):
            refs.extend(item for item in raw if isinstance(item, str) and item)
    return list(dict.fromkeys(refs))


def _causal_confidence_basis(
    strongest: Mapping[str, object] | None,
    *,
    supported: int,
    refuted: int,
    unresolved: int,
    korean: bool,
) -> str:
    claim = strongest.get("temporal_claim") if strongest is not None else None
    claim_map = claim if isinstance(claim, Mapping) else {}
    evidence = (
        f"grade={_answer_text(claim_map.get('evidence_grade'))}, "
        f"samples={_answer_text(claim_map.get('sample_count'))}, "
        f"correlation={_answer_text(claim_map.get('correlation'))}, "
        f"lag={_answer_text(claim_map.get('lag_seconds'))}s"
        if claim_map
        else ("검증된 strongest temporal claim 없음" if korean else "no strongest temporal claim")
    )
    prefix = "- 신뢰도 근거" if korean else "- Confidence basis"
    return (
        f"{prefix}: supported={supported}, refuted={refuted}, unresolved={unresolved}; {evidence}"
    )


def _change_activity_lines(
    output: Mapping[str, object] | None,
    *,
    korean: bool,
) -> tuple[list[str], list[str]]:
    if output is None:
        return (
            [
                "- 변경 이력 query가 이 조사에 포함되지 않았습니다."
                if korean
                else "- A change-history query was not included in this investigation."
            ],
            [],
        )
    rows = output.get("rows")
    if not isinstance(rows, list) or not rows:
        complete = output.get("source_complete") is True
        return (
            [
                (
                    "- 같은 대상과 시간 범위에서 일치하는 Activity Log 이벤트가 없습니다."
                    if korean
                    else (
                        "- No matching Activity Log event was found for the same target and window."
                    )
                )
                if complete
                else (
                    "- Activity Log 근거가 불완전하거나 unavailable 상태입니다."
                    if korean
                    else "- Activity Log evidence is incomplete or unavailable."
                )
            ],
            [],
        )
    lines: list[str] = []
    evidence_refs: list[str] = []
    for row in rows[:8]:
        if not isinstance(row, Mapping):
            continue
        values = row.get("values")
        if not isinstance(values, Mapping):
            continue
        actor = (
            "/".join(
                value
                for value in (
                    _answer_text(values.get("actor_kind"), fallback=""),
                    _answer_text(values.get("actor_ref"), fallback=""),
                )
                if value
            )
            or "unavailable"
        )
        lines.append(
            f"- {_answer_text(values.get('occurred_at'))}: "
            f"operation=`{_answer_text(values.get('operation'))}`, "
            f"status=`{_answer_text(values.get('status'))}`, actor=`{actor}`, "
            f"correlation=`{_answer_text(values.get('correlation_ref'), fallback='unavailable')}`"
        )
        refs = values.get("evidence_refs")
        if isinstance(refs, list):
            evidence_refs.extend(item for item in refs if isinstance(item, str) and item)
    if not lines:
        lines.append(
            "- Activity Log 행을 안전하게 해석할 수 없습니다."
            if korean
            else "- Activity Log rows could not be interpreted safely."
        )
    return lines, list(dict.fromkeys(evidence_refs))


def _causal_hypothesis_strength(hypothesis: Mapping[str, object]) -> tuple[int, int, float]:
    claim = hypothesis.get("temporal_claim")
    if not isinstance(claim, Mapping):
        return (0, 0, 0.0)
    grade = claim.get("evidence_grade")
    grade_rank = (
        {"predictive_precedence": 2, "association": 1}.get(grade, 0)
        if isinstance(grade, str)
        else 0
    )
    sample_count = claim.get("sample_count")
    correlation = claim.get("correlation")
    return (
        grade_rank,
        sample_count if isinstance(sample_count, int) and not isinstance(sample_count, bool) else 0,
        abs(float(correlation)) if isinstance(correlation, int | float) else 0.0,
    )


def _causal_hypothesis_lines(
    hypotheses: list[Mapping[str, object]],
    *,
    korean: bool,
) -> list[str]:
    lines: list[str] = []
    for hypothesis in hypotheses:
        claim = hypothesis.get("temporal_claim")
        claim_map = claim if isinstance(claim, Mapping) else {}
        falsifiers = claim_map.get("falsifiers")
        falsifier_text = (
            ", ".join(str(item) for item in falsifiers if isinstance(item, str))
            if isinstance(falsifiers, list)
            else ""
        )
        evidence = (
            f"grade={_answer_text(claim_map.get('evidence_grade'))}, "
            f"samples={_answer_text(claim_map.get('sample_count'))}, "
            f"correlation={_answer_text(claim_map.get('correlation'))}, "
            f"lag={_answer_text(claim_map.get('lag_seconds'))}s"
            if claim_map
            else ("검증된 시간 근거 없음" if korean else "no verified temporal evidence")
        )
        if falsifier_text:
            evidence += f", falsifiers={falsifier_text}"
        lines.append(
            f"- `{_answer_text(hypothesis.get('hypothesis_id'))}` - "
            f"`{_answer_text(hypothesis.get('status'))}` - {evidence}"
        )
    return lines


def _causal_limitations(
    comparison: Mapping[str, object],
    hypotheses: list[Mapping[str, object]],
) -> list[str]:
    values: list[str] = []
    reason = comparison.get("reason")
    if isinstance(reason, str) and reason:
        values.append(reason)
    for hypothesis in hypotheses:
        raw = hypothesis.get("limitations")
        if isinstance(raw, list):
            values.extend(item for item in raw if isinstance(item, str) and item)
    return list(dict.fromkeys(values))


def _hypothesis_names(hypotheses: list[Mapping[str, object]], *, korean: bool) -> str:
    names = [f"`{_answer_text(item.get('hypothesis_id'))}`" for item in hypotheses]
    return ", ".join(names) if names else ("없음" if korean else "none")


def _answer_text(value: object, *, fallback: str = "unknown") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:512]
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return fallback


def _answer_measure(value: object, unit: str) -> str:
    rendered = _answer_text(value, fallback="unavailable")
    return f"{rendered} {unit}".strip()


def _answer_window(start: object, end: object) -> str:
    return f"{_answer_text(start)} to {_answer_text(end)}"


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
    evidence_refs: Sequence[str],
) -> dict[str, object]:
    return {
        "node_id": node_id,
        "evidence_refs": list(evidence_refs),
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
    document_messages = {
        "semantic_governed_documents_unavailable": (
            "관리되는 문서 검색 기능을 사용할 수 없어 요청을 보류했습니다.",
            "The request was held because governed document retrieval is unavailable.",
        ),
        "semantic_governed_documents_incomplete": (
            "문서 검색 범위가 불완전하여 요청을 보류했습니다.",
            "The request was held because governed document retrieval was incomplete.",
        ),
        "semantic_governed_documents_empty": (
            "접근 가능한 범위에서 관련 문서 발췌문을 찾지 못해 요청을 보류했습니다.",
            "The request was held because no admissible document excerpt was found.",
        ),
    }
    if reason_code in document_messages:
        korean_message, english_message = document_messages[reason_code]
        return korean_message if locale.casefold().startswith("ko") else english_message
    if reason_code == "semantic_model_identity_unavailable":
        return (
            "모델 인증을 확인할 수 없어 요청을 보류했습니다. 인증을 복구한 후 다시 시도해 주세요."
            if locale.casefold().startswith("ko")
            else (
                "The request was held because model authentication is unavailable. "
                "Restore the configured identity and try again."
            )
        )
    if reason_code == "semantic_exact_source_unavailable":
        return (
            "차단됨: 정확한 원본을 사용할 수 없습니다."
            if locale.casefold().startswith("ko")
            else "Blocked: the exact source is unavailable."
        )
    if reason_code == "semantic_knowledge_source_status_unavailable":
        return (
            "사용 불가: 검증된 지식 원본 상태 기능이 바인딩되지 않았습니다."
            if locale.casefold().startswith("ko")
            else "Unavailable: no verified knowledge-source status capability is bound."
        )
    messages = {
        "answered": "The verified result is ready.",
        "direct_response": "The direct response is ready.",
        "held": "The request was held because verified evidence is unavailable.",
        "clarification": "The request needs clarification before it can run.",
        "unsupported": "The request is not supported by a verified capability.",
        "action_draft": "The request produced a review-only action draft.",
        "cancelled": "The request was cancelled.",
    }
    korean_messages = {
        "answered": "검증된 결과를 준비했습니다.",
        "direct_response": "직접 답변을 준비했습니다.",
        "held": "검증된 근거를 사용할 수 없어 요청을 보류했습니다.",
        "clarification": "요청을 수행하려면 추가 확인이 필요합니다.",
        "unsupported": "검증된 기능으로 답할 수 없는 요청입니다.",
        "action_draft": "요청을 검토 전용 작업 초안으로 만들었습니다.",
        "cancelled": "요청이 취소되었습니다.",
    }
    selected = korean_messages if locale.casefold().startswith("ko") else messages
    return f"{selected.get(disposition, selected['held'])} ({reason_code})"


def _continuity_terminal_answer(
    locale: str,
    disposition: str,
    reason_code: str,
    *,
    unavailable_reason: SemanticUnavailableReason | None,
) -> str:
    """Render a useful hold without upgrading evidence or action authority."""

    korean = locale.casefold().startswith("ko")
    limitation = _continuity_limitation(locale, reason_code)
    if disposition == "unsupported":
        if korean:
            return (
                "현재 확인된 내용: 이 요청을 처리할 검증된 FDAI 기능을 찾지 못했습니다.\n"
                f"제한 사항: {limitation}\n"
                "다음 안전 단계: 대상 리소스 또는 서비스, 확인할 시간 범위, 원하는 읽기 결과를 "
                "구체적으로 지정해 주세요.\n"
                "정확도 안내: 이 응답은 운영 사실에 대한 추정이 아니며 어떤 변경도 승인하지 "
                "않습니다."
            )
        return (
            "Confirmed status: no verified FDAI capability matched this request.\n"
            f"Limitation: {limitation}\n"
            "Safe next step: specify the target resource or service, the time window to inspect, "
            "and the read-only result you need.\n"
            "Accuracy notice: this response makes no operational factual inference and authorizes "
            "no change."
        )
    if unavailable_reason == "semantic_planner_unavailable":
        if korean:
            return (
                "현재 확인된 내용: 필요한 FDAI 내부 구성 요소가 이 턴을 완료하지 못했습니다.\n"
                f"제한 사항: {limitation}\n"
                "다음 안전 단계: 잠시 후 같은 범위로 다시 시도하고, 문제가 계속되면 런타임 "
                "준비 상태와 모델 및 저장소 상태를 확인해 주세요.\n"
                "정확도 안내: 운영 상태나 원인을 추정하지 않았으며 이 응답은 어떤 변경도 "
                "승인하지 않습니다."
            )
        return (
            "Confirmed status: a required FDAI internal component could not complete this turn.\n"
            f"Limitation: {limitation}\n"
            "Safe next step: retry with the same scope, then inspect runtime readiness plus model "
            "and store health if the issue continues.\n"
            "Accuracy notice: FDAI made no inference about operational state or cause, and this "
            "response authorizes no change."
        )
    if korean:
        return (
            "현재 확인된 내용: 검증된 답변을 만들 충분한 권위 있는 근거가 없습니다.\n"
            f"제한 사항: {limitation}\n"
            "다음 안전 단계: 범위와 시간 구간을 확인한 뒤 등록된 읽기 전용 조사를 통해 "
            "현재 상태, 변경 이력 및 관련 근거를 수집해 주세요.\n"
            "정확도 안내: 정확하지 않을 수 있는 답을 사실처럼 제시하지 않았습니다. FDAI는 "
            "이 경로를 개선 중이며 이 응답은 어떤 변경도 승인하지 않습니다."
        )
    return (
        "Confirmed status: authoritative evidence is insufficient for a verified answer.\n"
        f"Limitation: {limitation}\n"
        "Safe next step: confirm the scope and time window, then use registered read-only "
        "investigations to collect current state, change history, and related evidence.\n"
        "Accuracy notice: FDAI did not present a potentially inaccurate conclusion as fact. "
        "This path is being improved, and this response authorizes no change."
    )


def _continuity_limitation(locale: str, reason_code: str) -> str:
    korean = locale.casefold().startswith("ko")
    if reason_code == "semantic_exact_source_unavailable":
        return (
            "정확한 권위 있는 원본을 사용할 수 없습니다."
            if korean
            else "The exact authoritative source is unavailable."
        )
    if reason_code == "semantic_knowledge_source_status_unavailable":
        return (
            "검증된 지식 원본 상태 기능을 사용할 수 없습니다."
            if korean
            else "The verified knowledge-source status capability is unavailable."
        )
    return reason_code


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


def _semantic_projection_id(projection: Mapping[str, object]) -> str:
    """Bind projection identity to the complete immutable event content."""
    request_id = projection.get("request_id")
    if not isinstance(request_id, str):
        raise ValueError("semantic projection request_id MUST be a string")
    projection_digest = content_digest(projection)
    return str(uuid5(_PROJECTION_NAMESPACE, f"{request_id}\0{projection_digest}"))


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
    if loaded.get("schema_version") == "1.3.0":
        return OPERATOR_PROJECTION_PRODUCER_V13.encode(loaded)
    if loaded.get("schema_version") == "1.6.0":
        return OPERATOR_PROJECTION_PRODUCER_V16.encode(loaded)
    return OPERATOR_PROJECTION_PRODUCER_V14.encode(loaded)


def _pantheon_assurance_case_id(purpose: str) -> str | None:
    prefix = "conversation-assurance:"
    if not purpose.startswith(prefix):
        return None
    case_id = purpose.removeprefix(prefix)
    if not case_id or len(case_id) > 192:
        raise SemanticTurnRejectedError("conversation_assurance_case_invalid")
    return case_id


def _validate_pantheon_assurance_result(result: Mapping[str, object]) -> None:
    required_mappings = (
        "pantheon_trace",
        "pantheon_observations",
        "pantheon_diagnostic",
    )
    if (
        result.get("schema_version") != "1.0.0"
        or not isinstance(result.get("answer"), str)
        or not result["answer"]
        or not isinstance(result.get("assessment_id"), str)
        or not isinstance(result.get("trace_receipt_id"), str)
        or any(not isinstance(result.get(key), Mapping) for key in required_mappings)
        or not isinstance(result.get("pantheon_semantic_reviews"), list)
        or result.get("execution_authority") is not False
    ):
        raise ValueError("Pantheon conversation assurance result is malformed")


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SemanticTurnRejectedError(f"{field.replace(' ', '_')}_invalid")
    return value.astimezone(UTC)


__all__ = [
    "PantheonAssuranceRuntime",
    "SemanticTurnProcessor",
    "SemanticTurnRejectedError",
    "SemanticTurnResultStore",
    "SemanticTurnRuntime",
]
