"""Named resource-group membership reads containment from the exact group object."""

from __future__ import annotations

from fdai.core.conversation.semantic_planning_frame_core import build_semantic_frame
from fdai.core.conversation.semantic_planning_models import (
    SemanticFrameProposal,
    SemanticOutputShape,
)
from fdai.core.conversation.semantic_planning_specialized_plans import (
    build_stated_value_filter_plan,
)
from fdai.core.conversation.session import Principal, Role
from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    canonical_json,
    content_digest,
)

from tests.conversation.semantic_reasoning_support import (
    NOW,
    PURPOSE,
    execute,
    fixture_gateway,
    names,
    plan_verifier,
    production_manifest,
)

_UTTERANCE = "rg-app 리소스 그룹에 있는 리소스의 상세 정보를 알려줘"


def _membership_plan(group: str = "rg-app") -> OntologyQueryPlan:
    manifest = production_manifest()
    utterance = _UTTERANCE.replace("rg-app", group)
    frame = build_semantic_frame(
        SemanticFrameProposal(
            operation=SemanticOperation.SELECT,
            subject_constraints=("Resource", group),
            measure_concepts=("parent_id", "type"),
            output_shape=SemanticOutputShape.PROPERTY_FILTERED_RESOURCES,
            investigation=None,
            confidence=0.9,
        ),
        utterance=utterance,
        context=(),
    )
    plan = build_stated_value_filter_plan(
        verifier=plan_verifier(),
        frame=frame,
        utterance=utterance,
        descriptors=manifest.descriptors,
        manifest=manifest,
        principal=Principal(id="operator", role=Role.READER),
        purpose=PURPOSE,
        evaluation_time=NOW,
    )
    assert plan is not None
    return plan


def _substring_plan(template: OntologyQueryPlan) -> OntologyQueryPlan:
    """The retired lexical membership read, kept only to prove the defect it had."""

    node = OntologyQueryNode(
        node_id="substring",
        kind=QueryNodeKind.OBJECT_SET,
        arguments_json=canonical_json(
            {
                "definition": {
                    "selector": {"kind": "object_type", "name": "Resource"},
                    "predicates": [
                        {"property": "parent_id", "operator": "contains", "equals": "rg-app"}
                    ],
                    "as_of": NOW.isoformat(),
                    "purpose": PURPOSE,
                    "limit": 1000,
                }
            }
        ),
        output_kind="query.table",
    )
    body = {
        **template.model_dump(mode="json", exclude={"nodes", "output_node_ids", "plan_digest"}),
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": ["substring"],
    }
    return OntologyQueryPlan.model_validate({**body, "plan_digest": content_digest(body)})


async def test_group_members_are_the_containment_closure_of_the_exact_group() -> None:
    plan = _membership_plan()
    execution = await execute(plan, await fixture_gateway())

    assert execution.status == "completed"
    assert names(execution, plan.output_node_ids[0]) == {
        "aks-prod-01",
        "kv-app",
        "snet-app",
        "sql-app",
        "vm-app-01",
        "vnet-app",
    }


async def test_parent_substring_would_leak_members_of_a_similarly_named_group() -> None:
    gateway = await fixture_gateway()
    membership = _membership_plan()
    substring = _substring_plan(membership)

    members = names(await execute(membership, gateway), membership.output_node_ids[0])
    leaked = names(await execute(substring, gateway), "substring")

    assert "vm-app-dev-01" in leaked
    assert "vm-app-dev-01" not in members


async def test_group_names_match_without_regard_to_case() -> None:
    plan = _membership_plan("RG-APP")
    execution = await execute(plan, await fixture_gateway())

    assert names(execution, plan.output_node_ids[0]) >= {"aks-prod-01", "vm-app-01"}
