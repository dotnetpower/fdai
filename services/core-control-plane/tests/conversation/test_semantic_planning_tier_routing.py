"""T1-first semantic planning and bounded T2 escalation tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.composition.semantic_query_model_targets import t1_model_targets, t2_model_targets
from fdai.core.conversation.semantic_planning import SemanticPlanningService
from fdai.core.conversation.semantic_planning_models import SemanticPlanningDisposition
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

    def propose_frame(self, **_kwargs: Any) -> Any:
        self.frame_calls += 1
        return self.frame

    def propose_plan(self, **_kwargs: Any) -> Any:
        self.plan_calls += 1
        return self.plan


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


def _service(t1: _Model, t2: _Model, manifest: Any) -> SemanticPlanningService:
    return SemanticPlanningService(
        model=t1,
        escalation_model=t2,
        manifests=_ManifestProvider(manifest),
        verifier=OntologyQueryPlanVerifier(available_kinds=(QueryNodeKind.OBJECT_SET,)),
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
