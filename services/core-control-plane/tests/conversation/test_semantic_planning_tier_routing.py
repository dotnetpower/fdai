"""T1-first semantic planning and bounded T2 escalation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.composition.semantic_query_model_targets import t1_model_targets, t2_model_targets
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import (
    BoundIncident,
    SemanticPlanningDisposition,
)
from fdai.core.conversation.semantic_runtime import SemanticConversationRuntime
from fdai.core.conversation.session import Principal, Role
from fdai.core.ontology_platform import (
    ObjectPredicate,
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    OntologyQueryPlanExecutor,
    OntologyQueryPlanVerifier,
    build_query_manifest,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_MAX_RECORDS,
    incident_evidence_function_type,
)
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    NarratorCandidate,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType, PropertyDecl, PropertyType
from fdai.shared.ontology.release import build_ontology_release
from fdai_service_contracts.ontology_query import QueryNodeKind

NOW = datetime(2026, 8, 14, tzinfo=UTC)
DIGEST = "sha256:" + ("a" * 64)


class _ManifestProvider:
    def __init__(self, manifest: Any) -> None:
        self._manifest = manifest

    def manifest_for(self, *, principal: Principal, purpose: str):  # type: ignore[no-untyped-def]
        return self._manifest


class _Model:
    def __init__(self, *, frame: object, plan: object) -> None:
        self.frame = frame
        self.plan = plan
        self.frame_calls = 0
        self.plan_calls = 0
        self.plan_evaluation_times: list[datetime] = []

    def propose_frame(self, **_kwargs: Any) -> Any:
        self.frame_calls += 1
        return self.frame

    def propose_plan(self, **kwargs: Any) -> Any:
        self.plan_calls += 1
        self.plan_evaluation_times.append(kwargs["evaluation_time"])
        return self.plan


class _AcceptingVerifier:
    def verify(self, _plan: object, *, manifest: object) -> None:
        assert manifest is not None


def _fixture() -> tuple[Any, ObjectSetDefinition]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "secret": PropertyDecl(type=PropertyType.STRING, access_scope=CeilingRole.OWNER),
        },
    )
    release = build_ontology_release(object_types=(resource,))
    manifest = build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
    )
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        predicates=(ObjectPredicate(property="id", equals="resource-a"),),
        as_of=NOW,
        purpose="operations-review",
        limit=10,
    )
    return manifest, definition


def _frame(**overrides: object) -> dict[str, object]:
    return {
        "operation": "select",
        "subject_constraints": ["Resource"],
        "measure_concepts": [],
        "temporal_scope": {},
        "output_shape": "resource_list",
        "evidence_requirements": ["authoritative_inventory"],
        "unresolved_terms": [],
        "clarification_requirements": [],
        "clarification": None,
        "confidence": 0.9,
        **overrides,
    }


def _plan(definition: ObjectSetDefinition) -> dict[str, object]:
    return {
        "nodes": [
            {
                "node_id": "resources",
                "kind": "object_set",
                "depends_on": [],
                "arguments": {"definition": definition.model_dump(mode="json")},
                "output_kind": "query.table",
            }
        ],
        "output_node_ids": ["resources"],
    }


def _function_plan(function_name: str, *, output_kind: str) -> dict[str, object]:
    return {
        "nodes": [
            {
                "node_id": "function-result",
                "kind": "function",
                "depends_on": [],
                "arguments": {
                    "function_name": function_name,
                    "arguments": {},
                    "dependency_arguments": {},
                },
                "output_kind": output_kind,
            }
        ],
        "output_node_ids": ["function-result"],
    }


def _aggregate_plan(definition: ObjectSetDefinition) -> dict[str, object]:
    plan = _plan(definition)
    plan["nodes"] = [
        *plan["nodes"],  # type: ignore[misc]
        {
            "node_id": "aggregate",
            "kind": "aggregate",
            "depends_on": ["resources"],
            "arguments": {"operation": "count", "group_by": [], "limit": 10},
            "output_kind": "query.table",
        },
    ]
    plan["output_node_ids"] = ["aggregate"]
    return plan


def _manifest_aggregate_plan() -> dict[str, object]:
    plan = _function_plan("query.manifest", output_kind="query.table")
    plan["nodes"] = [
        *plan["nodes"],  # type: ignore[misc]
        {
            "node_id": "aggregate",
            "kind": "aggregate",
            "depends_on": ["function-result"],
            "arguments": {"operation": "count", "group_by": [], "limit": 10},
            "output_kind": "query.table",
        },
    ]
    plan["output_node_ids"] = ["aggregate"]
    return plan


def _service(t1: _Model, t2: _Model, manifest: Any) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
        now=lambda: NOW,
    )


def _run(service: SemanticPlanningService):  # type: ignore[no-untyped-def]
    return service.plan(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )


def test_valid_t1_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_t1_clarification_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            unresolved_terms=["resource"],
            clarification_requirements=["subject"],
            clarification="Which resource do you mean?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert t1.plan_calls == 0
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


@pytest.mark.parametrize("requirement", ("principal_scope", "purpose"))
def test_t1_server_bound_clarification_retries_only_frame_with_t2(requirement: str) -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(
            unresolved_terms=[requirement],
            clarification_requirements=[requirement],
            clarification="Which server context should I use?",
        ),
        plan=_plan(definition),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (1, 0)


def test_unavailable_t1_frame_retries_only_frame_with_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=None, plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (1, 0)


def test_invalid_t1_plan_retries_only_plan_with_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan={"nodes": [], "output_node_ids": []})
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 1)
    assert t1.plan_evaluation_times == [NOW]
    assert t2.plan_evaluation_times == [NOW]


def test_mismatched_specialized_t1_plan_retries_only_plan_with_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(output_shape="resource_list"),
        plan=_function_plan("query.manifest", output_kind="query.table"),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 1)


def test_matching_specialized_t1_plan_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    manifest_plan = _function_plan("query.manifest", output_kind="query.table")
    t1 = _Model(frame=_frame(output_shape="ontology_manifest"), plan=manifest_plan)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_incident_function_cannot_satisfy_resource_frame() -> None:
    manifest, definition = _fixture()
    t1 = _Model(
        frame=_frame(output_shape="resource_list"),
        plan=_function_plan("query.incident_evidence", output_kind="incident.evidence"),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 1)


def _incident_evidence_plan(*, incident_id: str, correlation_id: str) -> dict[str, object]:
    plan = _function_plan("query.incident_evidence", output_kind="incident.evidence")
    node = plan["nodes"][0]  # type: ignore[index]
    node["arguments"]["arguments"] = {  # type: ignore[index]
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "limit": 50,
    }
    return plan


def _incident_service(plan: dict[str, object], manifest: Any) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=_Model(frame=_frame(output_shape="incident_evidence"), plan=plan),
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )


def _incident_arguments(outcome: Any) -> dict[str, Any]:
    assert outcome.plan is not None
    return dict(outcome.plan.nodes[0].arguments["arguments"])


def test_anchored_conversation_never_retargets_a_read_of_another_incident() -> None:
    """Retargeting would answer about one incident while the operator asked about another."""
    manifest, _ = _fixture()
    service = _incident_service(
        _incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000701",
            correlation_id="another-incident",
        ),
        manifest,
    )

    outcome = service.plan(
        utterance="Report what the evidence for incident 0701 establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    arguments = _incident_arguments(outcome)
    assert arguments["incident_id"] == "00000000-0000-0000-0000-000000000701"
    assert arguments["correlation_id"] == "another-incident"


def _anchored_fixture() -> Any:
    """One manifest that actually offers the incident-evidence capability."""
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={"id": PropertyDecl(type=PropertyType.STRING, required=True)},
    )
    function = incident_evidence_function_type()
    release = build_ontology_release(object_types=(resource,), function_types=(function,))
    return build_query_manifest(
        release=release,
        principal_role=CeilingRole.READER,
        purposes=("operations-review",),
        principal_scope_digest=DIGEST,
        object_types=(resource,),
        functions=(function,),
    )


def _anchored_service(manifest: Any, plan: dict[str, object] | None) -> tuple[Any, Any]:
    model = _Model(frame=_frame(output_shape="incident_evidence"), plan=plan)
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    return service, model


def test_anchored_incident_read_is_built_from_the_binding_without_a_plan_proposal() -> None:
    manifest = _anchored_fixture()
    service, model = _anchored_service(manifest, None)

    outcome = service.plan(
        utterance="Report what the evidence for this incident establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 0
    assert outcome.plan is not None
    node = outcome.plan.nodes[0]
    assert node.arguments["function_name"] == "query.incident_evidence"
    assert node.arguments["arguments"] == {
        "incident_id": "00000000-0000-0000-0000-000000000702",
        "correlation_id": "bound-incident",
        "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
    }
    assert outcome.execution_authority is False


def test_bound_read_ignores_every_identity_the_frame_and_proposal_carry() -> None:
    """Only the binding may name the incident, however many the turn puts in reach."""
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            subject_constraints=[
                "00000000-0000-0000-0000-000000000703",
                "frame-supplied-incident",
            ],
        ),
        plan=_incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000704",
            correlation_id="proposal-supplied-incident",
        ),
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Report what the evidence for this incident establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 0
    assert _incident_arguments(outcome) == {
        "incident_id": "00000000-0000-0000-0000-000000000702",
        "correlation_id": "bound-incident",
        "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
    }


@pytest.mark.parametrize(
    ("incident_id", "correlation_id"),
    [
        ("", "bound-incident"),
        ("   ", "bound-incident"),
        ("00000000-0000-0000-0000-000000000702", ""),
        ("00000000-0000-0000-0000-000000000702", "   "),
    ],
)
def test_bound_incident_refuses_an_identity_it_cannot_anchor(
    incident_id: str, correlation_id: str
) -> None:
    """A blank identity would anchor the read to every incident at once."""
    with pytest.raises(ValueError):
        BoundIncident(incident_id=incident_id, correlation_id=correlation_id)


def test_unanchored_incident_frame_still_asks_the_planner() -> None:
    manifest = _anchored_fixture()
    service, model = _anchored_service(
        manifest,
        _incident_evidence_plan(
            incident_id="00000000-0000-0000-0000-000000000701",
            correlation_id="another-incident",
        ),
    )

    outcome = service.plan(
        utterance="Report what the evidence for incident 0701 establishes.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 1
    assert _incident_arguments(outcome)["correlation_id"] == "another-incident"


def test_anchored_turn_about_something_else_still_asks_the_planner() -> None:
    manifest, definition = _fixture()
    model = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Which storage accounts allow public network access?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert model.plan_calls == 1
    assert outcome.plan is not None
    assert outcome.plan.nodes[0].kind.value == "object_set"


def test_anchored_turn_never_asks_which_incident_it_is_already_anchored_to() -> None:
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            unresolved_terms=["this incident"],
            clarification_requirements=["incident_reference"],
            clarification="Which incident should I investigate?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="이 인시던트의 근거로 확인되는 사실을 보고해줘.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert outcome.clarification is None


def test_anchored_turn_still_clarifies_a_requirement_the_binding_cannot_answer() -> None:
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="incident_evidence",
            unresolved_terms=["this incident", "requests"],
            clarification_requirements=["incident_reference", "measure"],
            clarification="Do you mean HTTP requests or support requests?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Report what this incident did to requests.",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Do you mean HTTP requests or support requests?"


def test_anchored_turn_keeps_an_incident_question_for_another_output_shape() -> None:
    """Only a read of the anchored incident is answered by the binding."""
    manifest = _anchored_fixture()
    model = _Model(
        frame=_frame(
            output_shape="resource_list",
            unresolved_terms=["this incident"],
            clarification_requirements=["incident_reference"],
            clarification="Which incident should I investigate?",
        ),
        plan=None,
    )
    service = SemanticPlanningService(
        model=model,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = service.plan(
        utterance="Which resources did this incident touch?",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
        purpose="operations-review",
        bound_incident=BoundIncident(
            incident_id="00000000-0000-0000-0000-000000000702",
            correlation_id="bound-incident",
        ),
    )

    assert outcome.disposition is SemanticPlanningDisposition.CLARIFICATION
    assert outcome.clarification == "Which incident should I investigate?"


def test_aggregation_frame_requires_aggregate_plan() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(output_shape="aggregation_table"), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_aggregate_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 1)


def test_specialized_function_may_feed_matching_aggregate_output() -> None:
    manifest, definition = _fixture()
    aggregate_plan = _manifest_aggregate_plan()
    t1 = _Model(frame=_frame(output_shape="aggregation_table"), plan=aggregate_plan)
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_property_filter_frame_requires_object_set_predicate() -> None:
    manifest, definition = _fixture()
    unfiltered = definition.model_copy(update={"predicates": ()})
    t1 = _Model(
        frame=_frame(output_shape="property_filtered_resources"),
        plan=_plan(unfiltered),
    )
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    service = SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=_AcceptingVerifier(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    outcome = _run(service)

    assert outcome.disposition is SemanticPlanningDisposition.PLANNED
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 1)


def test_scope_denial_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    hidden = definition.model_copy(
        update={"predicates": (ObjectPredicate(property="secret", equals="value"),)}
    )
    t1 = _Model(frame=_frame(), plan=_plan(hidden))
    t2 = _Model(frame=_frame(), plan=_plan(definition))

    outcome = _run(_service(t1, t2, manifest))

    assert outcome.disposition is SemanticPlanningDisposition.UNSUPPORTED
    assert outcome.reason == "semantic_scope_denied"
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


async def test_evidence_execution_hold_never_invokes_t2() -> None:
    manifest, definition = _fixture()
    t1 = _Model(frame=_frame(), plan=_plan(definition))
    t2 = _Model(frame=_frame(), plan=_plan(definition))
    runtime = SemanticConversationRuntime(
        planner=_service(t1, t2, manifest),
        executor=OntologyQueryPlanExecutor(handlers={}, now=lambda: NOW),
    )

    result = await runtime.handle(
        utterance="Show matching resources",
        prior_turns=(),
        principal=Principal(id="operator", role=Role.READER),
    )

    assert result.disposition == "held"
    assert (t1.frame_calls, t1.plan_calls) == (1, 1)
    assert (t2.frame_calls, t2.plan_calls) == (0, 0)


def test_composition_separates_t1_and_t2_candidates() -> None:
    resolved = ResolvedModels(
        schema_version="1.0.0",
        region="example-region",
        subscription_id="00000000-0000-0000-0000-000000000000",
        deployer_object_id="00000000-0000-0000-0000-000000000000",
        mixed_model_mode="hil-only",
        capabilities=(
            ResolvedCapability(
                name="t1.judge",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="gpt-5.4-mini",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.primary",
                status=CapabilityStatus.RESOLVED,
                publisher="OpenAI",
                family="gpt-4.1",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
            ResolvedCapability(
                name="t2.reasoner.secondary",
                status=CapabilityStatus.RESOLVED,
                publisher="Anthropic",
                family="claude-opus-4",
                sku="Standard",
                capacity_tpm=1000,
                invocation="always",
            ),
        ),
        narrator_candidates=(
            NarratorCandidate(
                endpoint="https://models.example.com",
                deployment="narrator-gpt-5-4-mini",
            ),
        ),
    )

    t1 = t1_model_targets(resolved, endpoint="https://models.example.com", endpoint_resolver=None)
    t2 = t2_model_targets(resolved, endpoint="https://models.example.com", endpoint_resolver=None)

    assert [target.deployment for target in t1] == ["narrator-gpt-5-4-mini"]
    assert [target.deployment for target in t2] == ["t2.reasoner.primary"]
