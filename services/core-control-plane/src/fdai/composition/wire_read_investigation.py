"""Production composition for resource-state investigation shadow parity."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fdai_service_contracts import OperationalActivityStatus, OperationalFreshness

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.interfaces import compile_interfaces
from fdai.core.ontology_platform.models import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
)
from fdai.core.ontology_platform.object_sets import ObjectSetService
from fdai.core.ontology_platform.query_gateway import (
    SecuredObjectSetQueryGateway,
    SecuredObjectSetQueryResult,
)
from fdai.core.ontology_platform.query_profiles import QueryProfile
from fdai.core.ontology_platform.semantic_plans import (
    ActiveSemanticCatalog,
    InterpretationCandidateSource,
    SemanticInterpretationCandidate,
    SemanticOperationClass,
    VerifiedInterpretationBasis,
    build_semantic_candidate,
    verify_semantic_candidate,
)
from fdai.core.ontology_platform.semantic_query import SemanticQueryService
from fdai.core.read_investigation.models import (
    ReadInvestigationBudget,
    ReadInvestigationOutcome,
    ReadInvestigationRequest,
    ReadInvestigationResult,
)
from fdai.core.read_investigation.planner import plan_read_investigation
from fdai.core.read_investigation.resource_state_shadow_service import (
    ShadowResourceStateComparisonService,
)
from fdai.core.read_investigation.routing import (
    classify_read_investigation_intent,
    resource_name_from_question,
)
from fdai.core.read_investigation.service import ReadInvestigationService
from fdai.core.read_investigation.shadow_sink import (
    ShadowComparisonSink,
    StateStoreShadowComparisonSink,
)
from fdai.delivery.operational_activity import (
    EventBusOperationalActivityPublisher,
    current_state_activity,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog, load_ontology_catalog
from fdai.shared.contracts.models import CeilingRole, OntologyFunctionType, OntologyRelease
from fdai.shared.contracts.registry import SchemaRegistry
from fdai.shared.ontology.acl import ProjectionRequest
from fdai.shared.providers.ontology_instance import OntologyInstanceStore
from fdai.shared.providers.read_investigation import (
    ReadInvestigationIntent,
    ReadInvestigationProvider,
    ResourceSelector,
)
from fdai.shared.providers.state_store import StateStore

_FUNCTION_NAME = "inventory.select_resources"
_PURPOSE = "operations-review"
_LOG = logging.getLogger(__name__)


class _ExactProfileCatalog(ActiveSemanticCatalog):
    def __init__(self, *, digest: str, candidate_digest: str) -> None:
        self._digest = digest
        self._candidate_digest = candidate_digest

    @property
    def digest(self) -> str:
        return self._digest

    def contains(self, candidate: SemanticInterpretationCandidate) -> bool:
        return candidate.candidate_digest == self._candidate_digest


class ResourceStateShadowHook:
    """Run one authoritative read and append ontology parity evidence in shadow."""

    def __init__(
        self,
        *,
        read_service: ReadInvestigationService,
        semantic_service: SemanticQueryService,
        function_type: OntologyFunctionType,
        release: OntologyRelease,
        shadow_service: ShadowResourceStateComparisonService,
        clock: Callable[[], datetime],
        activity_publisher: EventBusOperationalActivityPublisher | None = None,
    ) -> None:
        self._read_service = read_service
        self._semantic_service = semantic_service
        self._function_type = function_type
        self._release = release
        self._shadow_service = shadow_service
        self._clock = clock
        self._activity_publisher = activity_publisher

    async def __call__(
        self,
        question: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return the authoritative resource-state answer and shadow disposition."""

        if (
            classify_read_investigation_intent(question)
            is not ReadInvestigationIntent.RESOURCE_STATE
        ):
            return None
        resource_name = resource_name_from_question(question)
        if resource_name is None:
            return None
        requester_ref = _reference("principal", context.get("user_id"), fallback="operator")
        conversation_ref = _reference(
            "conversation",
            context.get("session_id"),
            fallback="unbound",
        )
        correlation_ref = _digest_ref("read-correlation", requester_ref, conversation_ref, question)
        request = ReadInvestigationRequest(
            requester_ref=requester_ref,
            conversation_ref=conversation_ref,
            correlation_ref=correlation_ref,
            intent=ReadInvestigationIntent.RESOURCE_STATE,
            selector=ResourceSelector(name=resource_name, scope_ref="scope:operator"),
            lookback_seconds=3_600,
            requested_evidence=(),
            budget=ReadInvestigationBudget(),
            idempotency_key=_digest_ref("read-request", requester_ref, conversation_ref, question),
            created_at=self._clock(),
        )
        await self._publish_activity(
            correlation_id=correlation_ref,
            status=OperationalActivityStatus.STARTED,
            freshness=OperationalFreshness.UNKNOWN,
        )
        try:
            authoritative = await self._read_service.execute(plan_read_investigation(request))
        except Exception:
            await self._publish_activity(
                correlation_id=correlation_ref,
                status=OperationalActivityStatus.FAILED,
                freshness=OperationalFreshness.UNAVAILABLE,
                reason_codes=("read_failed",),
            )
            raise
        activity_status, freshness, reason_codes = _read_activity_outcome(authoritative.outcome)
        duration_ms = max(
            0,
            round((authoritative.finished_at - authoritative.started_at).total_seconds() * 1000),
        )
        await self._publish_activity(
            correlation_id=correlation_ref,
            status=activity_status,
            freshness=freshness,
            evidence_count=len(authoritative.evidence_refs),
            duration_ms=duration_ms,
            reason_codes=reason_codes,
        )
        shadow_outcome = "not_attempted"
        shadow_persistence = "not_attempted"
        if (
            authoritative.outcome is ReadInvestigationOutcome.MATCHED
            and authoritative.resolution.resource is not None
        ):
            try:
                query_result, semantic_receipt, profile, semantic_plan = await self._query_shadow(
                    authoritative
                )
                attempt = await self._shadow_service.compare(
                    existing_result=authoritative,
                    query_result=query_result,
                    semantic_receipt=semantic_receipt,
                    query_profile=profile,
                    semantic_plan=semantic_plan,
                    principal_ref=requester_ref,
                    correlation_ref=correlation_ref,
                )
                shadow_outcome = attempt.receipt.outcome.value
                shadow_persistence = attempt.persistence.value
            except Exception as exc:  # noqa: BLE001 - shadow never rewrites the answer
                shadow_outcome = "error"
                shadow_persistence = "failed"
                _LOG.warning(
                    "resource_state_shadow_execution_failed",
                    extra={
                        "correlation_id": correlation_ref,
                        "error_kind": type(exc).__name__,
                    },
                )
        return _render_result(
            authoritative,
            question=question,
            shadow_outcome=shadow_outcome,
            shadow_persistence=shadow_persistence,
        )

    async def _publish_activity(
        self,
        *,
        correlation_id: str,
        status: OperationalActivityStatus,
        freshness: OperationalFreshness,
        evidence_count: int = 0,
        duration_ms: int | None = None,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        if self._activity_publisher is None:
            return
        await self._activity_publisher.publish(
            current_state_activity(
                correlation_id=correlation_id,
                status=status,
                freshness=freshness,
                evidence_count=evidence_count,
                duration_ms=duration_ms,
                reason_codes=reason_codes,
            )
        )

    async def _query_shadow(self, authoritative: ReadInvestigationResult):  # type: ignore[no-untyped-def]
        resource = authoritative.resolution.resource
        if resource is None:  # pragma: no cover - caller checks exact resolution
            raise ValueError("resource-state shadow requires one resolved resource")
        definition = ObjectSetDefinition(
            selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
            predicates=(ObjectPredicate(property="id", equals=resource.resource_ref),),
            as_of=self._clock(),
            purpose=_PURPOSE,
            limit=1,
        )
        profile = QueryProfile.from_release(
            release=self._release,
            name="resource-state",
            version="1.0.0",
            function_type=self._function_type,
            object_set_template=definition,
            purpose=_PURPOSE,
        )
        arguments = {"object_set": definition.model_dump(mode="json")}
        candidate = build_semantic_candidate(
            source=InterpretationCandidateSource.LEXICAL,
            operation_class=SemanticOperationClass.QUERY,
            target_ref=profile.function_ref,
            arguments=arguments,
            semantic_catalog_digest=profile.profile_digest,
            input_text=f"resource-state-shadow:{resource.resource_ref}",
            score=1.0,
            unresolved_terms=(),
        )
        semantic_plan = verify_semantic_candidate(
            candidate,
            release=self._release,
            active_semantic_catalog=_ExactProfileCatalog(
                digest=profile.profile_digest,
                candidate_digest=candidate.candidate_digest,
            ),
            basis=VerifiedInterpretationBasis.EXACT_CATALOG,
            basis_ref=f"catalog:{profile.profile_digest}",
        )
        result, receipt = await self._semantic_service.execute(
            profile=profile,
            plan=semantic_plan,
            context=FunctionInvocationContext(
                caller_agent="Heimdall",
                caller_role=CeilingRole.READER,
                purposes=(_PURPOSE,),
                evidence_refs=authoritative.evidence_refs,
            ),
        )
        return result, receipt, profile, semantic_plan


def build_resource_state_shadow_hook(
    *,
    provider: ReadInvestigationProvider,
    shadow_sink: ShadowComparisonSink,
    ontology_release: OntologyRelease,
    ontology_catalog: OntologyCatalog,
    ontology_store: OntologyInstanceStore,
    clock: Callable[[], datetime] | None = None,
    activity_publisher: EventBusOperationalActivityPublisher | None = None,
) -> ResourceStateShadowHook:
    """Compose exact-release resource-state shadowing from production read seams."""

    function_type = next(
        (item for item in ontology_catalog.function_types if item.name == _FUNCTION_NAME),
        None,
    )
    if function_type is None:
        raise ValueError("resource-state shadow FunctionType is unavailable")
    evaluation_clock = clock or (lambda: datetime.now(tz=UTC))
    interfaces = compile_interfaces(
        interfaces=ontology_catalog.interface_types,
        implementations=ontology_catalog.interface_implementations,
        object_types=ontology_catalog.object_types,
        release=ontology_release,
    )
    gateway = SecuredObjectSetQueryGateway(
        service=ObjectSetService(
            store=ontology_store,
            interfaces=interfaces,
            object_type_names=frozenset(item.name for item in ontology_catalog.object_types),
        ),
        object_types={item.name: item for item in ontology_catalog.object_types},
        ontology_release=ontology_release,
        evaluation_cutoff=evaluation_clock,
    )
    registry = OntologyFunctionRegistry(release=ontology_release)

    async def select_resources(
        arguments: Mapping[str, Any],
        invocation: FunctionInvocationContext,
    ) -> SecuredObjectSetQueryResult:
        definition = ObjectSetDefinition.model_validate(arguments["object_set"])
        return await gateway.materialize(
            definition,
            projection_request=ProjectionRequest(
                caller_role=invocation.caller_role,
                declared_purposes=frozenset(invocation.purposes),
            ),
        )

    registry.register_contextual(function_type, select_resources)
    return ResourceStateShadowHook(
        read_service=ReadInvestigationService(provider, clock=evaluation_clock),
        semantic_service=SemanticQueryService(release=ontology_release, registry=registry),
        function_type=function_type,
        release=ontology_release,
        shadow_service=ShadowResourceStateComparisonService(sink=shadow_sink),
        clock=evaluation_clock,
        activity_publisher=activity_publisher,
    )


def compose_resource_state_shadow_hook(
    *,
    provider: ReadInvestigationProvider | None,
    state_store: StateStore,
    ontology_release: OntologyRelease | None,
    ontology_store: OntologyInstanceStore | None,
    schema_registry: SchemaRegistry,
    catalog_root: Path,
    clock: Callable[[], datetime] | None = None,
    activity_publisher: EventBusOperationalActivityPublisher | None = None,
) -> ResourceStateShadowHook | None:
    """Compose the optional production hook only when every read seam is available."""

    if provider is None or ontology_release is None or ontology_store is None:
        return None
    catalog = load_ontology_catalog(
        catalog_root,
        schema_registry=schema_registry,
        probes_root=(catalog_root / "probes" if (catalog_root / "probes").is_dir() else None),
    )
    return build_resource_state_shadow_hook(
        provider=provider,
        shadow_sink=StateStoreShadowComparisonSink(store=state_store),
        ontology_release=ontology_release,
        ontology_catalog=catalog,
        ontology_store=ontology_store,
        clock=clock,
        activity_publisher=activity_publisher,
    )


def _read_activity_outcome(
    outcome: ReadInvestigationOutcome,
) -> tuple[OperationalActivityStatus, OperationalFreshness, tuple[str, ...]]:
    if outcome is ReadInvestigationOutcome.MATCHED:
        return OperationalActivityStatus.COMPLETED, OperationalFreshness.FRESH, ()
    if outcome is ReadInvestigationOutcome.PARTIAL:
        return (
            OperationalActivityStatus.DEGRADED,
            OperationalFreshness.UNKNOWN,
            (outcome.value,),
        )
    if outcome in {ReadInvestigationOutcome.UNAVAILABLE, ReadInvestigationOutcome.TIMED_OUT}:
        return (
            OperationalActivityStatus.DEGRADED,
            OperationalFreshness.UNAVAILABLE,
            (outcome.value,),
        )
    return OperationalActivityStatus.COMPLETED, OperationalFreshness.UNKNOWN, (outcome.value,)


def _render_result(
    result: ReadInvestigationResult,
    *,
    question: str,
    shadow_outcome: str,
    shadow_persistence: str,
) -> dict[str, Any]:
    resource = result.resolution.resource
    states = tuple(
        record.state
        for envelope in result.evidence
        for record in envelope.records
        if record.state is not None
    )
    state = states[0] if len(states) == 1 else None
    name = (
        resource.name
        if resource is not None
        else resource_name_from_question(question) or "resource"
    )
    korean = any("가" <= character <= "힣" for character in question)
    if state is not None:
        answer = (
            f"{name}의 현재 상태는 {state}입니다." if korean else f"{name} is currently {state}."
        )
    else:
        answer = (
            f"{name}의 현재 상태 근거를 확인할 수 없습니다."
            if korean
            else f"Current state evidence is unavailable for {name}."
        )
    return {
        "answer": answer,
        "facts": {
            "status": result.outcome.value,
            "resource_ref": resource.resource_ref if resource is not None else None,
            "state": state,
            "evidence_refs": result.evidence_refs,
            "shadow_outcome": shadow_outcome,
            "shadow_persistence": shadow_persistence,
            "execution_authority": False,
        },
    }


def _reference(prefix: str, value: object, *, fallback: str) -> str:
    text = str(value or fallback).strip()
    return text if text.startswith(f"{prefix}:") else f"{prefix}:{text}"


def _digest_ref(prefix: str, *values: str) -> str:
    digest = hashlib.sha256("\x00".join(values).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


__all__ = [
    "ResourceStateShadowHook",
    "build_resource_state_shadow_hook",
    "compose_resource_state_shadow_hook",
]
