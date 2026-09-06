"""End-to-end semantic runtime tests for governed document evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fdai.composition.wire_semantic_query import build_semantic_query_runtime
from fdai.core.conversation.adaptive_models import AdaptiveEvidence
from fdai.core.conversation.adaptive_service import AdaptiveUnavailable
from fdai.core.conversation.semantic_planning_models import SemanticOutputShape
from fdai.core.conversation.semantic_runtime import _query_output_incomplete
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform.governed_document_queries import (
    GovernedDocumentCollection,
    GovernedDocumentExcerpt,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.query_values import QueryTable
from fdai.core.ontology_platform.service_health_queries import (
    SERVICE_HEALTH_MEASURE_CONCEPTS,
    ServiceHealthCollection,
)
from fdai.rule_catalog.schema.ontology_catalog import OntologyCatalog
from fdai.rule_catalog.schema.property_semantic import empty_property_semantic_registry
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.testing.ontology_instance import InMemoryOntologyInstanceStore
from fdai_core_service.semantic_turn_processor import (
    _project_runtime_result,
    _projected_answer_evidence_is_complete,
)
from fdai_service_contracts import OperatorRole, SemanticTurnPrincipal, SemanticTurnRequest
from fdai_service_contracts.ontology_query import QueryNodeKind

NOW = datetime(2026, 9, 6, 5, 0, tzinfo=UTC)


class _Model:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": [],
            "measure_concepts": ["document.governed_excerpt"],
            "temporal_scope": {},
            "output_shape": "governed_document_excerpts",
            "evidence_requirements": ["governed_documents.explicit"],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.99,
        }

    def propose_plan(self, **_kwargs: Any) -> None:
        return None


class _Reader:
    def __init__(self, result: GovernedDocumentCollection) -> None:
        self.result = result

    async def search(
        self,
        *,
        query: str,
        principal_ref: str,
        principal_role: CeilingRole,
        principal_groups: frozenset[str],
        purpose: str,
        limit: int,
    ) -> GovernedDocumentCollection:
        assert query == "What does the recovery runbook require?"
        assert principal_ref == "operator-a"
        assert principal_role is CeilingRole.READER
        assert principal_groups == frozenset({"group:responders"})
        assert purpose == "operations-review"
        assert limit == 8
        return self.result


class _FailingReader:
    async def search(self, **_kwargs: Any) -> GovernedDocumentCollection:
        raise RuntimeError("document provider unavailable")


class _MixedModel:
    def propose_frame(self, **_kwargs: Any) -> dict[str, object]:
        return {
            "operation": "select",
            "subject_constraints": ["Resource"],
            "measure_concepts": list(SERVICE_HEALTH_MEASURE_CONCEPTS),
            "temporal_scope": {},
            "output_shape": "subscription_service_health",
            "evidence_requirements": [
                "authoritative_service_health",
                "governed_documents.optional",
            ],
            "unresolved_terms": [],
            "clarification_requirements": [],
            "clarification": None,
            "investigation": None,
            "confidence": 0.99,
        }

    def propose_plan(self, **_kwargs: Any) -> None:
        return None


class _ServiceHealthReader:
    async def read_active(self) -> ServiceHealthCollection:
        return ServiceHealthCollection(
            observations=(),
            observed_at=NOW,
            complete=True,
            limitation=None,
            attempt_ref="service-health:attempt",
        )


class _AdaptiveEvidenceProbe:
    def __init__(self) -> None:
        self.evidence: AdaptiveEvidence | None = None

    def social_profile(self, *_args: Any) -> None:
        return None

    async def respond(self, **kwargs: Any) -> AdaptiveUnavailable:
        self.evidence = await kwargs["read_evidence"]("What does the recovery runbook require?")
        return AdaptiveUnavailable(reason="probe_complete", observations=())


def _collection(
    *,
    excerpts: tuple[GovernedDocumentExcerpt, ...],
    complete: bool = True,
    limitation: str | None = None,
) -> GovernedDocumentCollection:
    return GovernedDocumentCollection(
        excerpts=excerpts,
        observed_at=NOW,
        complete=complete,
        limitation=limitation,
        index_generation="document-index:sha256:" + ("a" * 64),
        access_scope_digest="sha256:" + ("b" * 64),
        retrieval_mode="hybrid",
    )


def test_contextual_completeness_ignores_optional_document_output() -> None:
    planning = SimpleNamespace(
        frame=SimpleNamespace(output_shape=SemanticOutputShape.CONTEXTUAL_RESOURCE_LIST),
        plan=SimpleNamespace(
            nodes=(
                SimpleNamespace(
                    node_id="operational",
                    kind=QueryNodeKind.FUNCTION,
                    arguments={"function_name": "query.contextual_resources"},
                ),
                SimpleNamespace(
                    node_id="documents",
                    kind=QueryNodeKind.FUNCTION,
                    arguments={"function_name": "query.governed_documents"},
                ),
            ),
            output_node_ids=("operational", "documents"),
        ),
    )
    execution = SimpleNamespace(
        results={
            "operational": SimpleNamespace(value=QueryTable(rows=(), complete=True)),
            "documents": SimpleNamespace(
                value=QueryTable(
                    rows=(),
                    complete=False,
                    truncation_reason="index_completeness_unverified",
                )
            ),
        }
    )

    assert _query_output_incomplete(planning, execution) is False


def _excerpt() -> GovernedDocumentExcerpt:
    return GovernedDocumentExcerpt(
        evidence_ref="document:sha256:" + ("c" * 64),
        document_revision="version:00000000-0000-0000-0000-000000000001:sha256:" + ("d" * 64),
        source_name="recovery-runbook.md",
        source_ref="document://recovery-runbook#restart",
        locator="section:restart",
        chunk_id="chunk-1",
        text="Verify the health probe before restarting.",
        content_digest="sha256:" + ("e" * 64),
        score=0.95,
    )


def _runtime(result: GovernedDocumentCollection):
    function_types = operational_function_types(())
    return build_semantic_query_runtime(
        model=_Model(),
        ontology_release=build_ontology_release(function_types=function_types),
        ontology_catalog=OntologyCatalog(
            object_types=(),
            interface_types=(),
            interface_implementations=(),
            link_types=(),
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=InMemoryOntologyInstanceStore(object_types=(), link_types=()),
        governed_document_reader=_Reader(result),
        now=lambda: NOW,
    )


def _mixed_runtime(
    result: GovernedDocumentCollection | None,
    *,
    bind_documents: bool = True,
    adaptive_service: Any = None,
):
    function_types = operational_function_types(())
    return build_semantic_query_runtime(
        model=_MixedModel(),
        ontology_release=build_ontology_release(function_types=function_types),
        ontology_catalog=OntologyCatalog(
            object_types=(),
            interface_types=(),
            interface_implementations=(),
            link_types=(),
            action_types=(),
            function_types=(),
            property_semantics=empty_property_semantic_registry(),
        ),
        ontology_store=InMemoryOntologyInstanceStore(object_types=(), link_types=()),
        governed_document_reader=(_Reader(result) if result is not None else _FailingReader())
        if bind_documents
        else None,
        service_health_reader=_ServiceHealthReader(),
        adaptive_service=adaptive_service,
        now=lambda: NOW,
    )


async def test_runtime_returns_document_grounded_answer_evidence() -> None:
    result = await _runtime(_collection(excerpts=(_excerpt(),))).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "answered"
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["evidence_mode"] == "document_grounded"
    assert result.execution is not None
    assert _projected_answer_evidence_is_complete(result, result.execution)
    table = result.execution.results["governed-documents"].value
    assert table.rows[1].values["evidence_ref"] == "document:sha256:" + ("c" * 64)


async def test_runtime_holds_required_document_answer_when_index_is_incomplete() -> None:
    result = await _runtime(
        _collection(
            excerpts=(_excerpt(),),
            complete=False,
            limitation="candidate_limit_reached",
        )
    ).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "held"
    assert result.reason == "semantic_governed_documents_incomplete"


async def test_runtime_holds_required_document_answer_when_no_excerpt_matches() -> None:
    result = await _runtime(_collection(excerpts=())).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "held"
    assert result.reason == "semantic_governed_documents_empty"


async def test_runtime_keeps_document_and_operational_authority_in_separate_lanes() -> None:
    result = await _mixed_runtime(_collection(excerpts=(_excerpt(),))).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "answered"
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["evidence_mode"] == "mixed_grounded"
    assert result.execution is not None
    assert result.execution.output_node_ids == (
        "subscription-service-health",
        "governed-documents",
    )


async def test_runtime_keeps_operational_answer_when_optional_document_provider_fails() -> None:
    result = await _mixed_runtime(None).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "answered"
    assert result.reason == "semantic_optional_governed_documents_unavailable"
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["status"] == "partial"
    assert result.intent_graph_evidence["evidence_mode"] == "partial"
    assert result.execution is not None
    assert _projected_answer_evidence_is_complete(result, result.execution)

    projected, _extensions = _project_runtime_result(
        SemanticTurnRequest(
            utterance="What does the recovery runbook require?",
            principal=SemanticTurnPrincipal(
                subject_id="operator-a",
                roles=(OperatorRole.READER,),
                groups=("group:responders",),
            ),
            session_id="session-a",
            turn_id="turn-a",
            turn_sequence=1,
            locale="en",
            purpose="operations-review",
            deadline_at=NOW + timedelta(seconds=30),
        ),
        result,
    )

    assert projected.disposition.value == "answered", projected.reason_code
    assert projected.checks_completed < projected.checks_total
    assert "Governed document retrieval was unavailable" in projected.answer


async def test_runtime_marks_incomplete_optional_document_evidence_partial() -> None:
    result = await _mixed_runtime(
        _collection(
            excerpts=(_excerpt(),),
            complete=False,
            limitation="index_completeness_unverified",
        )
    ).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "answered"
    assert result.reason == "semantic_optional_governed_documents_incomplete"
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["status"] == "partial"
    assert result.intent_graph_evidence["evidence_mode"] == "partial"
    assert result.execution is not None
    assert _projected_answer_evidence_is_complete(result, result.execution)

    projected, _extensions = _project_runtime_result(
        SemanticTurnRequest(
            utterance="What does the recovery runbook require?",
            principal=SemanticTurnPrincipal(
                subject_id="operator-a",
                roles=(OperatorRole.READER,),
                groups=("group:responders",),
            ),
            session_id="session-a",
            turn_id="turn-a",
            turn_sequence=0,
            locale="en",
            purpose="operations-review",
            deadline_at=NOW + timedelta(seconds=30),
        ),
        result,
    )

    assert projected.disposition.value == "answered", projected.reason_code
    assert projected.reason_code == "semantic_answer_partial"
    assert projected.checks_completed == projected.checks_total
    assert "Document coverage is incomplete" in projected.answer


async def test_adaptive_evidence_keeps_operational_results_when_optional_document_fails() -> None:
    adaptive = _AdaptiveEvidenceProbe()

    result = await _mixed_runtime(None, adaptive_service=adaptive).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "held"
    assert result.reason == "probe_complete"
    assert adaptive.evidence is not None
    assert adaptive.evidence.status == "answered"
    assert adaptive.evidence.limitation == "semantic_optional_governed_documents_unavailable"
    assert "governed-document" not in adaptive.evidence.content
    assert adaptive.evidence.evidence_refs


async def test_runtime_keeps_operational_answer_when_optional_binding_is_absent() -> None:
    result = await _mixed_runtime(None, bind_documents=False).handle(
        utterance="What does the recovery runbook require?",
        prior_turns=(),
        principal=Principal(
            id="operator-a",
            role=Role.READER,
            groups=frozenset({"group:responders"}),
        ),
    )

    assert result.disposition == "answered"
    assert result.reason == "semantic_optional_governed_documents_unavailable"
    assert result.intent_graph_evidence is not None
    assert result.intent_graph_evidence["status"] == "partial"
    assert result.intent_graph_evidence["evidence_mode"] == "partial"
    assert result.execution is not None
    assert result.execution.output_node_ids == ("subscription-service-health",)
    assert _projected_answer_evidence_is_complete(result, result.execution)

    projected, _extensions = _project_runtime_result(
        SemanticTurnRequest(
            utterance="What does the recovery runbook require?",
            principal=SemanticTurnPrincipal(
                subject_id="operator-a",
                roles=(OperatorRole.READER,),
                groups=("group:responders",),
            ),
            session_id="session-a",
            turn_id="turn-a",
            turn_sequence=0,
            locale="en",
            purpose="operations-review",
            deadline_at=NOW + timedelta(seconds=30),
        ),
        result,
    )

    assert projected.disposition.value == "answered"
    assert projected.reason_code == "semantic_answer_partial"
    assert projected.checks_completed == projected.checks_total
    assert "Governed document retrieval was unavailable" in projected.answer
